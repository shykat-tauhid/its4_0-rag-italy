import { Component, OnDestroy, inject } from '@angular/core';
import { AppStateService } from '../app-state.service';

export interface LanguageOption {
  code: string;
  nativeName: string;
  translatedName: string;
}

export const LANGUAGES: LanguageOption[] = [
  { code: 'it', nativeName: 'Italiano', translatedName: '' },
  { code: 'uk', nativeName: 'Українська', translatedName: 'Ucraino' },
  { code: 'zh', nativeName: '中文', translatedName: 'Cinese' },
  { code: 'bn', nativeName: 'বাংলা', translatedName: 'Bengali' },
  { code: 'tl', nativeName: 'Tagalog', translatedName: 'Filippino' },
  { code: 'ar', nativeName: 'العربية', translatedName: 'Arabo' },
];

const RTL = ['ar'];

export const RETURN_DELAY_MS = 600;

@Component({
  selector: 'app-language',
  standalone: true,
  templateUrl: './language.component.html',
  styleUrls: ['./language.component.css']
})
export class Language implements OnDestroy {
  public state = inject(AppStateService);

  readonly languages = LANGUAGES;
  private timer?: ReturnType<typeof setTimeout>;

  isSelected(code: string): boolean {
    return (this.state.selectedLanguage() ?? 'it') === code;
  }

  dirOf(code: string): 'rtl' | 'ltr' {
    return RTL.includes(code) ? 'rtl' : 'ltr';
  }

  selectLanguage(lang: LanguageOption): void {
    this.state.setLanguage(lang.code);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.state.closeLanguage(), RETURN_DELAY_MS);
  }

  back(): void {
    clearTimeout(this.timer);
    this.state.closeLanguage();
  }

  ngOnDestroy(): void {
    clearTimeout(this.timer);
  }
}
