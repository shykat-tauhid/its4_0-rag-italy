import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  ViewEncapsulation,
  computed,
  effect,
  input,
  model,
  output,
  signal,
  untracked,
  viewChild
} from '@angular/core';
import Keyboard from 'simple-keyboard';
import { KeyboardConfig, keyboardConfig } from './keyboard-layouts';
import { EditorOptions, EditorState, commitRaw, isControlKey, pickCandidate, pressKey } from './keyboard-editor';
import { Candidate, PinyinIme, loadPinyinIme } from './pinyin-ime';

@Component({
  selector: 'app-virtual-keyboard',
  standalone: true,
  template: `
    <div class="vk" dir="ltr" #panel>
      <div class="vk-inner">
        @if (composition()) {
          <div class="vk-ime">
            <span class="vk-ime-pinyin" lang="zh-Latn">{{ composition() }}</span>
            <div class="vk-ime-list" lang="zh" role="listbox">
              @for (candidate of candidates(); track $index) {
                <button type="button" class="vk-ime-candidate" role="option"
                        (pointerdown)="$event.preventDefault()" (click)="pick(candidate)">{{ candidate.word }}</button>
              } @empty {
                <span class="vk-ime-empty">{{ ime() ? '—' : '…' }}</span>
              }
            </div>
          </div>
        }
        <div #keyboard class="simple-keyboard"></div>
      </div>
    </div>
  `,
  styleUrls: ['./virtual-keyboard.component.css'],
  encapsulation: ViewEncapsulation.None
})
export class VirtualKeyboard implements AfterViewInit, OnDestroy {
  readonly lang = input<string | null>(null);
  readonly target = input.required<HTMLInputElement>();
  readonly value = model('');

  readonly enter = output<void>();
  readonly close = output<void>();

  private keyboardEl = viewChild.required<ElementRef<HTMLDivElement>>('keyboard');
  private panelEl = viewChild.required<ElementRef<HTMLDivElement>>('panel');

  private keyboard?: Keyboard;
  private resizeObserver?: ResizeObserver;
  private readonly latin = signal(false);
  private readonly config = computed(() => keyboardConfig(this.lang(), this.latin()));
  readonly ime = signal<PinyinIme | null>(null);
  readonly composition = signal('');
  readonly candidates = computed(() => this.ime()?.candidates(this.composition()) ?? []);
  private caret = 0;
  private shiftOnce = false;
  private capsLock = false;

  constructor() {
    effect(() => {
      const config = this.config();
      untracked(() => {
        this.composition.set('');
        this.keyboard?.setOptions(this.layoutOptions(config));
      });
    });

    effect(() => {
      if (this.config().ime !== 'pinyin' || this.ime()) return;
      loadPinyinIme()
        .then((ime) => this.ime.set(ime))
        .catch((err) => console.error('Dizionario pinyin non disponibile:', err));
    });

    effect(() => {
      const text = this.value();
      untracked(() => {
        if (this.keyboard && this.keyboard.getInput() !== text) {
          this.keyboard.setInput(text);
          this.keyboard.setCaretPosition(text.length);
          this.caret = text.length;
        }
      });
    });
  }

  ngAfterViewInit(): void {
    this.keyboard = new Keyboard(this.keyboardEl().nativeElement, {
      ...this.layoutOptions(this.config()),
      preventMouseDownDefault: true,
      onChange: () => this.syncKeyboard(this.value(), this.caret),
      onKeyPress: (button: string) => this.onKeyPress(button)
    });
    this.caret = this.value().length;
    this.keyboard.setInput(this.value());
    this.keyboard.setCaretPosition(this.caret);

    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(([entry]) =>
        document.documentElement.style.setProperty('--kb-h', `${Math.ceil(entry.borderBoxSize[0].blockSize)}px`)
      );
      this.resizeObserver.observe(this.panelEl().nativeElement);
    }
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.keyboard?.destroy();
    document.documentElement.style.removeProperty('--kb-h');
  }

  pick(candidate: Candidate): void {
    this.apply(pickCandidate(this.editorState(), candidate));
  }

  private layoutOptions(config: KeyboardConfig) {
    return {
      layout: config.layout,
      layoutName: this.capsLock ? 'shift' : 'default',
      display: config.display
    };
  }

  private editorOptions(): EditorOptions {
    const config = this.config();
    return {
      ime: config.ime !== null,
      punctuation: config.punctuation,
      firstCandidate: (composition) => this.ime()?.candidates(composition, 1)[0] ?? null
    };
  }

  private editorState(): EditorState {
    const text = this.value();
    const caret = this.keyboard?.getCaretPosition() ?? text.length;
    return { text, caret: Math.min(caret, text.length), composition: this.composition() };
  }

  private apply(next: EditorState): void {
    this.composition.set(next.composition);
    this.caret = next.caret;
    if (next.text !== this.value()) this.value.set(next.text);
    this.syncKeyboard(next.text, next.caret);
  }

  private syncKeyboard(text: string, caret: number): void {
    this.keyboard?.setInput(text);
    this.keyboard?.setCaretPosition(caret);
    const el = this.target();
    if (el.value !== text) el.value = text;
    el.setSelectionRange(caret, caret);
  }

  private onKeyPress(button: string): void {
    switch (button) {
      case '{enter}':
        if (this.composition()) this.apply(commitRaw(this.editorState()));
        else this.enter.emit();
        return;
      case '{close}':
        this.close.emit();
        return;
      case '{abc}':
        this.latin.update((v) => !v);
        return;
      case '{shift}':
        this.shiftOnce = !this.shiftOnce;
        this.capsLock = false;
        this.applyShift();
        return;
      case '{lock}':
        this.capsLock = !this.capsLock;
        this.shiftOnce = false;
        this.applyShift();
        return;
    }

    this.apply(pressKey(this.editorState(), button, this.editorOptions()));
    if (this.shiftOnce && !isControlKey(button)) {
      this.shiftOnce = false;
      this.applyShift();
    }
  }

  private applyShift(): void {
    const shifted = this.shiftOnce || this.capsLock;
    this.keyboard?.setOptions({ layoutName: shifted ? 'shift' : 'default' });
    this.keyboard?.removeButtonTheme('{shift} {lock}', 'vk-on');
    if (this.shiftOnce) this.keyboard?.addButtonTheme('{shift}', 'vk-on');
    if (this.capsLock) this.keyboard?.addButtonTheme('{lock}', 'vk-on');
  }
}
