import { Component, computed, inject } from '@angular/core';
import { AppStateService } from '../app-state.service';

const TAP_TEXTS: Record<string, string> = {
  it: 'Tocca lo schermo per iniziare',
  uk: 'Торкніться екрана, щоб почати',
  zh: '触摸屏幕开始',
  bn: 'শুরু করতে স্ক্রিন স্পর্শ করুন',
  tl: 'Pindutin ang screen para magsimula',
  ar: 'المس الشاشة للبدء',
};

@Component({
  selector: 'app-welcome',
  standalone: true,
  templateUrl: './welcome.component.html',
  styleUrls: ['./welcome.component.css']
})
export class Welcome {
  public state = inject(AppStateService);

  readonly tapText = computed(() => TAP_TEXTS[this.state.selectedLanguage() ?? 'it'] ?? TAP_TEXTS['it']);

  start(): void {
    this.state.currentStep.set('choice');
  }

  openLanguage(event: Event): void {
    event.stopPropagation();
    this.state.openLanguageFromWelcome();
  }
}
