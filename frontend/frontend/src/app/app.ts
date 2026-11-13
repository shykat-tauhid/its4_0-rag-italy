import { Component, inject } from '@angular/core';
import { AppStateService } from './app-state.service';
import { AccessibilityService } from './accessibility.service';
import { Welcome } from './welcome.component/welcome.component';
import { Language } from './language.component/language.component';
import { Choice } from './choice.component/choice.component';
import { Service } from './service.component/service.component';
import { Chatbot } from './chatbot.component/chatbot.component';
import { WebApp } from './webapp.component/webapp.component';
import { Accessibility } from './accessibility.component/accessibility.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [Welcome, Language, Choice, Service, Chatbot, WebApp, Accessibility],
  template: `
    @if (state.currentStep() !== 'webapp') {
      <div class="stripe" aria-hidden="true"></div>
    }
    <main>
      @switch (state.currentStep()) {
        @case ('welcome') { <app-welcome /> }
        @case ('language') { <app-language /> }
        @case ('choice') { <app-choice /> }
        @case ('services') { <app-service /> }
        @case ('chatbot') { <app-chatbot /> }
        @case ('webapp') { <app-webapp /> }
      }
    </main>
    @if (state.currentStep() !== 'webapp') {
      <app-accessibility />
    }
  `
})
export class App {
  public state = inject(AppStateService);
  private a11y = inject(AccessibilityService);
}
