import { Component, ElementRef, HostListener, OnDestroy, computed, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppStateService, ChatForm, ChatMessage, ChatSource } from '../app-state.service';
import { CHAT_API_URL, CONVERSATION_PDF_API_URL } from '../api.config';
import { VirtualKeyboard } from '../virtual-keyboard.component/virtual-keyboard.component';
import { LinkViewer } from '../link-viewer.component/link-viewer.component';
import { LinkViewerService, ViewerLink } from '../link-viewer.service';
import { printPages, releasePages, renderPdfData } from '../link-viewer.component/pdf-pages';

type StreamEvent =
  | { type: 'token'; text: string }
  | { type: 'sources'; sources: ChatSource[]; forms: ChatForm[] }
  | { type: 'done' }
  | { type: 'error'; message: string };

type PrintStatus = 'idle' | 'printing' | 'done' | 'error';

// How long the outcome of a print ("printed", "failed") stays on the button.
const PRINT_STATUS_MS = 8000;

@Component({
  selector: 'app-chatbot',
  standalone: true,
  imports: [FormsModule, VirtualKeyboard, LinkViewer],
  templateUrl: './chatbot.component.html',
  styleUrls: ['./chatbot.component.css']
})
export class Chatbot implements OnDestroy {
  public state = inject(AppStateService);
  public viewer = inject(LinkViewerService);

  private messagesBox = viewChild<ElementRef<HTMLElement>>('messagesBox');
  private chatInput = viewChild<ElementRef<HTMLInputElement>>('chatInput');

  readonly newMessage = signal('');
  readonly waiting = signal(false);
  readonly keyboardOpen = signal(false);
  readonly printStatus = signal<PrintStatus>('idle');
  // The same PDF-to-images printing used by the viewer (replaceable in tests).
  readonly pdf = { render: renderPdfData, print: printPages, release: releasePages };
  private printStatusTimer?: ReturnType<typeof setTimeout>;

  // Only once the user has asked something: the welcome message alone is not worth printing.
  readonly canPrint = computed(
    () =>
      !this.waiting() &&
      this.printStatus() !== 'printing' &&
      this.state.chatMessages().some((msg) => msg.sender === 'user')
  );

  readonly printLabel = computed(() => {
    switch (this.printStatus()) {
      case 'printing':
        return this.state.t('viewerPrinting');
      case 'done':
        return this.state.t('printConversationDone');
      case 'error':
        return this.state.t('viewerPrintError');
      default:
        return this.state.t('printConversation');
    }
  });

  constructor() {
    effect(() => {
      this.state.chatMessages();
      this.waiting();
      const box = this.messagesBox()?.nativeElement;
      if (box) {
        queueMicrotask(() => box.scrollTop = box.scrollHeight);
      }
    });
  }

  closeKeyboard(): void {
    this.keyboardOpen.set(false);
    this.chatInput()?.nativeElement.blur();
  }

  // Only a touch outside the chat, the keyboard and the open file or page closes the keyboard.
  @HostListener('document:pointerdown', ['$event'])
  onPointerDown(event: PointerEvent): void {
    if (!this.keyboardOpen()) return;
    const target = event.target as Element | null;
    if (target?.closest('app-virtual-keyboard, .chatbot-container, app-link-viewer')) return;
    this.closeKeyboard();
  }

  // Files and sources open next to the chat, half the screen each, not in another tab.
  openLink(event: Event, link: ViewerLink): void {
    event.preventDefault();
    this.viewer.open(link);
  }

  ngOnDestroy(): void {
    this.viewer.close();
    clearTimeout(this.printStatusTimer);
  }

  /**
   * Prints the conversation for the office operator: the backend builds a PDF with the user's
   * language on the left and the Italian translation on the right, the pages are rendered here
   * as images and sent to the kiosk printer, like the forms in the viewer.
   */
  async printConversation(): Promise<void> {
    if (!this.canPrint()) return;
    clearTimeout(this.printStatusTimer);
    this.printStatus.set('printing');

    const messages = this.state.chatMessages();
    const first = messages.findIndex((msg) => msg.sender === 'user');
    const payload = {
      messages: messages
        .slice(first)
        .filter((msg) => !msg.pending && msg.text.trim())
        .map((msg) => ({ role: msg.sender === 'user' ? 'user' : 'assistant', content: msg.text }))
    };

    let pages: string[] = [];
    try {
      const response = await fetch(CONVERSATION_PDF_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      pages = await this.pdf.render(await response.arrayBuffer());
      await this.pdf.print(pages);
      this.printStatus.set('done');
    } catch (err) {
      console.error('Stampa conversazione non riuscita:', err);
      this.printStatus.set('error');
    } finally {
      this.pdf.release(pages);
      this.printStatusTimer = setTimeout(() => this.printStatus.set('idle'), PRINT_STATUS_MS);
    }
  }

  goBack(): void {
    this.state.currentStep.set('choice');
  }

  goToLanguageSelection(): void {
    this.state.goToLanguage('choice');
  }

  async sendMessage(): Promise<void> {
    const text = this.newMessage().trim();
    if (!text || this.waiting()) return;

    this.closeKeyboard();
    this.state.addMessage({ text, sender: 'user' });
    this.newMessage.set('');
    this.waiting.set(true);

    let reply: ChatMessage = { text: '', sender: 'bot', pending: true };
    this.state.addMessage(reply);

    const payload = {
      message: text,
      language: this.state.selectedLanguage(),
      service: this.state.activeService(),
      session_id: this.state.sessionId
    };

    try {
      const response = await fetch(`${CHAT_API_URL}/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (line.trim()) reply = this.handleEvent(reply, JSON.parse(line));
        }
      }
    } catch (err) {
      console.error('Errore backend Python:', err);
      reply = this.state.updateMessage(reply, { text: this.state.t('chatError') });
    } finally {
      this.state.updateMessage(reply, { pending: false });
      this.waiting.set(false);
    }
  }

  private handleEvent(reply: ChatMessage, event: StreamEvent): ChatMessage {
    if (event.type === 'token') {
      return this.state.updateMessage(reply, { text: reply.text + event.text, pending: false });
    }
    if (event.type === 'sources') {
      return this.state.updateMessage(reply, { sources: event.sources, forms: event.forms });
    }
    if (event.type === 'error') {
      throw new Error(event.message);
    }
    return reply;
  }
}
