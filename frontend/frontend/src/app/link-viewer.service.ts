import { Injectable, signal } from '@angular/core';

export interface ViewerLink {
  url: string;
  title: string;
  /** The saved text of the page (a Markdown file), for sites that cannot be shown in a frame. */
  copy?: string | null;
}

// The kiosk has no tabs: every link, file or page opens inside it, in the link viewer. The chat
// shows it next to itself, half the screen each; the web app shows it over the whole screen.
@Injectable({
  providedIn: 'root'
})
export class LinkViewerService {
  readonly link = signal<ViewerLink | null>(null);

  open(link: ViewerLink): void {
    this.link.set(link);
  }

  close(): void {
    this.link.set(null);
  }
}
