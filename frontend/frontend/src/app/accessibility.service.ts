import { Injectable, effect, signal } from '@angular/core';
import { readStorage, writeStorage } from './storage';

export type FontChoice = 'default' | 'dyslexic' | 'hyper';
export type ColorVision = 'none' | 'deutan' | 'tritan' | 'achro' | 'contrast' | 'soft';
export type Theme = 'auto' | 'light' | 'dark';

export interface A11yPrefs {
  fs: number;
  font: FontChoice;
  cvd: ColorVision;
  theme: Theme;
  spacing: boolean;
  links: boolean;
  motion: boolean;
}

// Same options, key and format as public/webapp/accessibility.js: the totem and the
// "Trova un ufficio" web app (loaded in an iframe) share one set of preferences.
export const A11Y_STORAGE_KEY = 'a11y-prefs-v1';
export const TEXT_STEPS = [85, 100, 115, 130, 150, 175, 200];
export const FONTS: FontChoice[] = ['default', 'dyslexic', 'hyper'];
export const COLOR_VISIONS: ColorVision[] = ['none', 'deutan', 'tritan', 'achro', 'contrast', 'soft'];
export const THEMES: Theme[] = ['auto', 'light', 'dark'];

export const DEFAULT_PREFS: A11yPrefs = {
  fs: 100, font: 'default', cvd: 'none', theme: 'auto', spacing: false, links: false, motion: false
};

@Injectable({
  providedIn: 'root'
})
export class AccessibilityService {
  readonly prefs = signal<A11yPrefs>(readPrefs());
  private readonly systemDark = window.matchMedia('(prefers-color-scheme: dark)');
  private readonly prefersDark = signal(this.systemDark.matches);

  constructor() {
    // "Auto" follows the system's light or dark mode, as in the web app.
    this.systemDark.addEventListener?.('change', (event) => this.prefersDark.set(event.matches));

    effect(() => {
      const p = this.prefs();
      const theme = p.theme === 'auto' ? (this.prefersDark() ? 'dark' : 'light') : p.theme;
      const root = document.documentElement;
      root.style.setProperty('--font-scale', String(p.fs / 100));
      root.dataset['font'] = p.font;
      root.dataset['cvd'] = p.cvd;
      root.dataset['theme'] = theme;
      root.dataset['spacing'] = p.spacing ? '1' : '0';
      root.dataset['links'] = p.links ? '1' : '0';
      root.dataset['motion'] = p.motion ? '1' : '0';
      writeStorage(A11Y_STORAGE_KEY, JSON.stringify(p));
    });

    // Changes made inside the web app iframe come back here.
    window.addEventListener('storage', (event) => {
      if (event.key === A11Y_STORAGE_KEY) {
        this.reload();
      }
    });
  }

  /** Reads the saved preferences again, e.g. after returning from the web app. */
  reload(): void {
    this.prefs.set(readPrefs());
  }

  set<K extends keyof A11yPrefs>(key: K, value: A11yPrefs[K]): void {
    this.prefs.update((p) => ({ ...p, [key]: value }));
  }

  toggle(key: 'spacing' | 'links' | 'motion'): void {
    this.prefs.update((p) => ({ ...p, [key]: !p[key] }));
  }

  increaseText(): void {
    this.stepText(1);
  }

  decreaseText(): void {
    this.stepText(-1);
  }

  reset(): void {
    this.prefs.set({ ...DEFAULT_PREFS });
  }

  private stepText(delta: number): void {
    this.prefs.update((p) => {
      const i = Math.min(Math.max(TEXT_STEPS.indexOf(p.fs) + delta, 0), TEXT_STEPS.length - 1);
      return { ...p, fs: TEXT_STEPS[i] };
    });
  }
}

function readPrefs(): A11yPrefs {
  let stored: Partial<A11yPrefs> = {};
  try {
    stored = JSON.parse(readStorage(A11Y_STORAGE_KEY) ?? '{}') ?? {};
  } catch {
  }
  return {
    fs: TEXT_STEPS.includes(Number(stored.fs)) ? Number(stored.fs) : DEFAULT_PREFS.fs,
    font: FONTS.includes(stored.font as FontChoice) ? stored.font as FontChoice : DEFAULT_PREFS.font,
    cvd: COLOR_VISIONS.includes(stored.cvd as ColorVision) ? stored.cvd as ColorVision : DEFAULT_PREFS.cvd,
    theme: THEMES.includes(stored.theme as Theme) ? stored.theme as Theme : DEFAULT_PREFS.theme,
    spacing: stored.spacing === true,
    links: stored.links === true,
    motion: stored.motion === true
  };
}
