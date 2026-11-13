import { Component, inject } from '@angular/core';
import { AppStateService, ServiceType } from '../app-state.service';

@Component({
  selector: 'app-service',
  standalone: true,
  templateUrl: './service.component.html',
  styleUrls: ['./service.component.css']
})
export class Service {
  public state = inject(AppStateService);

  selectService(service: ServiceType): void {
    this.state.startService(service);
  }

  goBack(): void {
    this.state.currentStep.set('choice');
  }

  goToLanguageSelection(): void {
    this.state.goToLanguage();
  }
}
