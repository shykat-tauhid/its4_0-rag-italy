import { Component, inject } from '@angular/core';
import { AppStateService } from '../app-state.service';

@Component({
  selector: 'app-choice',
  standalone: true,
  templateUrl: './choice.component.html',
  styleUrls: ['./choice.component.css']
})
export class Choice {
  public state = inject(AppStateService);

  // Straight to the chat: the services page is kept, but for now there is only Anagrafica.
  openAssistant(): void {
    this.state.startService('anagrafica');
  }

  openOffices(): void {
    this.state.currentStep.set('webapp');
  }

  goBack(): void {
    this.state.currentStep.set('welcome');
  }

  goToLanguageSelection(): void {
    this.state.goToLanguage('choice');
  }
}
