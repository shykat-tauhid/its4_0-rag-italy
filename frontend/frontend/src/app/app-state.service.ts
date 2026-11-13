import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export type Step = 'welcome' | 'language' | 'choice' | 'services' | 'chatbot' | 'webapp';
export type ServiceType = 'anagrafica' | 'affitto';
export type Translations = Record<string, Record<string, string>>;

const RTL_LANGUAGES = ['ar'];

export interface ChatSource {
  number: number;
  title: string;
  kind: string;
  url: string | null;
  /** The saved text of the page, shown when the site cannot be opened inside the kiosk. */
  copy?: string | null;
}

export interface ChatForm {
  id: string;
  title: string;
  url: string;
}

export interface ChatMessage {
  text: string;
  sender: 'bot' | 'user';
  sources?: ChatSource[];
  forms?: ChatForm[];
  pending?: boolean;
}

@Injectable({
  providedIn: 'root'
})
export class AppStateService {
  private http = inject(HttpClient);

  readonly currentStep = signal<Step>('welcome');
  readonly selectedLanguage = signal<string | null>(null);
  readonly activeService = signal<ServiceType | null>(null);
  readonly chatMessages = signal<ChatMessage[]>([]);
  readonly translations = signal<Translations>({});
  sessionId: string = crypto.randomUUID();

  readonly isRtl = computed(() => RTL_LANGUAGES.includes(this.selectedLanguage() ?? ''));
  readonly dir = computed(() => (this.isRtl() ? 'rtl' : 'ltr'));

  constructor() {
    this.loadTranslations();
  }

  loadTranslations(): void {
    this.http.get<Translations>('assets/translation.json').subscribe({
      next: (data) => this.translations.set(data),
      error: (err) => console.error('Errore nel caricamento delle traduzioni:', err)
    });
  }

  t(key: string, lang: string | null = this.selectedLanguage()): string {
    const all = this.translations();
    return all[lang || 'it']?.[key] || all['it']?.[key] || key;
  }

  setLanguage(langCode: string): void {
    this.selectedLanguage.set(langCode);
    document.documentElement.lang = langCode;
  }

  readonly languageReturnStep = signal<Step>('welcome');

  openLanguageFromWelcome(): void {
    this.languageReturnStep.set('welcome');
    this.currentStep.set('language');
  }

  goToLanguage(returnStep: Step = 'services'): void {
    this.languageReturnStep.set(returnStep);
    this.currentStep.set('language');
    this.activeService.set(null);
    this.chatMessages.set([]);
    this.newSession();
  }

  closeLanguage(): void {
    this.currentStep.set(this.languageReturnStep());
  }

  newSession(): void {
    this.sessionId = crypto.randomUUID();
  }

  startService(service: ServiceType): void {
    this.activeService.set(service);
    const welcomeKey = service === 'anagrafica' ? 'chatWelcomeAnagrafica' : 'chatWelcomeAffitto';
    this.chatMessages.set([{ text: this.t(welcomeKey), sender: 'bot' }]);
    this.newSession();
    this.currentStep.set('chatbot');
  }

  addMessage(message: ChatMessage): void {
    this.chatMessages.update((list) => [...list, message]);
  }

  updateMessage(message: ChatMessage, changes: Partial<ChatMessage>): ChatMessage {
    const updated = { ...message, ...changes };
    this.chatMessages.update((list) => list.map((m) => (m === message ? updated : m)));
    return updated;
  }
}
