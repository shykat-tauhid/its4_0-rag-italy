import { Component, HostListener, OnDestroy, computed, inject } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { AppStateService } from '../app-state.service';
import { AccessibilityService } from '../accessibility.service';
import { LinkViewer } from '../link-viewer.component/link-viewer.component';
import { LinkViewerService } from '../link-viewer.service';

export function webappUrl(lang: string | null): string {
  return `webapp/index.html?lang=${encodeURIComponent(lang ?? 'it')}&embed=1`;
}

export const WEBAPP_BACK_MESSAGE = 'tramite:back';
export const WEBAPP_LANG_MESSAGE = 'tramite:lang';
/** A link of the web app: the kiosk has no tabs, so it opens over the web app. */
export const WEBAPP_OPEN_MESSAGE = 'tramite:open';

@Component({
  selector: 'app-webapp',
  standalone: true,
  imports: [LinkViewer],
  template: `
    <iframe class="webapp" [src]="src()" [title]="state.t('optOffices')" allow="geolocation"></iframe>
    @if (viewer.link()) {
      <div class="webapp-viewer" [attr.dir]="state.dir()"><app-link-viewer /></div>
    }
  `,
  styles: `
    :host { display: block; }
    /* Over the whole web app, with a small margin. */
    .webapp-viewer {
      position: fixed;
      inset: 0;
      z-index: 1000;
      box-sizing: border-box;
      padding: 24px;
      background: color-mix(in srgb, var(--c-hd) 82%, transparent);
    }
    .webapp-viewer app-link-viewer { height: 100%; }
    .webapp {
      display: block;
      width: 100vw;
      height: 100vh;
      height: 100dvh;
      border: 0;
    }
  `
})
export class WebApp implements OnDestroy {
  public state = inject(AppStateService);
  public viewer = inject(LinkViewerService);
  private sanitizer = inject(DomSanitizer);
  private a11y = inject(AccessibilityService);

  readonly src = computed(() => this.sanitizer.bypassSecurityTrustResourceUrl(webappUrl(this.state.selectedLanguage())));

  ngOnDestroy(): void {
    this.viewer.close();
  }

  @HostListener('window:message', ['$event'])
  onMessage(event: MessageEvent): void {
    if (event.origin !== location.origin) return;
    // The accessibility options may have been changed inside the web app.
    if (event.data?.type === WEBAPP_BACK_MESSAGE) {
      this.a11y.reload();
      this.state.currentStep.set('choice');
    } else if (event.data?.type === WEBAPP_LANG_MESSAGE) {
      this.a11y.reload();
      this.state.goToLanguage('webapp');
    } else if (event.data?.type === WEBAPP_OPEN_MESSAGE && typeof event.data.url === 'string') {
      this.viewer.open({ url: event.data.url, title: String(event.data.title || event.data.url) });
    }
  }
}
