import { Component, ElementRef, HostListener, inject, signal, viewChild } from '@angular/core';
import { AppStateService } from '../app-state.service';
import {
  A11yPrefs,
  AccessibilityService,
  COLOR_VISIONS,
  ColorVision,
  FONTS,
  FontChoice,
  TEXT_STEPS,
  THEMES,
  Theme
} from '../accessibility.service';

const FONT_INFO: Record<FontChoice, { label: string; family: string }> = {
  'default': { label: 'a11y.fontDefault', family: 'Titillium Web' },
  'dyslexic': { label: 'a11y.fontDys', family: 'OpenDyslexic' },
  'hyper': { label: 'a11y.fontHyper', family: 'Atkinson Hyperlegible' }
};

const COLOR_INFO: Record<ColorVision, { label: string; desc: string; swatch: string[] }> = {
  'none': { label: 'a11y.cvdNone', desc: 'a11y.cvdNoneD', swatch: ['#0066cc', '#008758', '#a12b2b'] },
  'deutan': { label: 'a11y.cvdDeutan', desc: 'a11y.cvdDeutanD', swatch: ['#0057b8', '#e69f00', '#b34700'] },
  'tritan': { label: 'a11y.cvdTritan', desc: 'a11y.cvdTritanD', swatch: ['#b8194a', '#1b7f4b', '#3b4048'] },
  'achro': { label: 'a11y.cvdAchro', desc: 'a11y.cvdAchroD', swatch: ['#111111', '#767676', '#dedede'] },
  'contrast': { label: 'a11y.cvdContrast', desc: 'a11y.cvdContrastD', swatch: ['#000000', '#ffd400', '#00e5ff'] },
  'soft': { label: 'a11y.cvdSoft', desc: 'a11y.cvdSoftD', swatch: ['#3d6b91', '#4f7f70', '#8a4a47'] }
};

const THEME_LABELS: Record<Theme, string> = {
  'auto': 'a11y.themeAuto',
  'light': 'a11y.themeLight',
  'dark': 'a11y.themeDark'
};

type SwitchKey = 'spacing' | 'links' | 'motion';

// Same panel and behaviour as the web app's (public/webapp/accessibility.js).
@Component({
  selector: 'app-accessibility',
  standalone: true,
  templateUrl: './accessibility.component.html',
  styleUrls: ['./accessibility.component.css']
})
export class Accessibility {
  public state = inject(AppStateService);
  public a11y = inject(AccessibilityService);
  private host = inject(ElementRef<HTMLElement>);
  private title = viewChild.required<ElementRef<HTMLElement>>('title');
  private fab = viewChild.required<ElementRef<HTMLButtonElement>>('fab');

  readonly open = signal(false);
  readonly announcement = signal('');
  readonly fonts = FONTS;
  readonly colorVisions = COLOR_VISIONS;
  readonly themes = THEMES;
  readonly fontInfo = FONT_INFO;
  readonly colorInfo = COLOR_INFO;
  readonly themeLabels = THEME_LABELS;
  readonly switches: { key: SwitchKey; label: string }[] = [
    { key: 'spacing', label: 'a11y.spacing' },
    { key: 'links', label: 'a11y.underline' },
    { key: 'motion', label: 'a11y.reduceMotion' }
  ];
  readonly minText = TEXT_STEPS[0];
  readonly maxText = TEXT_STEPS[TEXT_STEPS.length - 1];

  toggle(): void {
    this.setOpen(!this.open());
  }

  close(): void {
    this.setOpen(false);
  }

  choose<K extends 'font' | 'cvd' | 'theme'>(key: K, value: A11yPrefs[K], label: string): void {
    this.a11y.set(key, value);
    this.announce('a11y.activated', { x: label });
  }

  flip(key: SwitchKey, label: string): void {
    this.a11y.toggle(key);
    this.announce(this.a11y.prefs()[key] ? 'a11y.toggleOn' : 'a11y.toggleOff', { x: label });
  }

  changeText(delta: number): void {
    if (delta > 0) this.a11y.increaseText(); else this.a11y.decreaseText();
    this.announce('a11y.sizeAnn', { n: String(this.a11y.prefs().fs) });
  }

  resetAll(): void {
    this.a11y.reset();
    this.announce('a11y.resetAnn');
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open()) this.close();
  }

  // A click outside closes the panel without taking the focus from what was clicked.
  @HostListener('document:pointerdown', ['$event'])
  onOutside(event: PointerEvent): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) {
      this.open.set(false);
    }
  }

  private setOpen(open: boolean): void {
    this.open.set(open);
    if (open) {
      setTimeout(() => this.title().nativeElement.focus());
    } else {
      this.fab().nativeElement.focus();
    }
  }

  private announce(key: string, values: Record<string, string> = {}): void {
    this.announcement.set(this.state.t(key).replace(/\{(\w+)\}/g, (m, k) => values[k] ?? m));
  }
}
