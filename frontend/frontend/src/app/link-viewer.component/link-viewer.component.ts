import { Component, OnDestroy, effect, inject, signal, untracked } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import QRCode from 'qrcode';
import { AppStateService } from '../app-state.service';
import { API_URL, EMBEDDABLE_API_URL } from '../api.config';
import { LinkViewerService, ViewerLink } from '../link-viewer.service';
import { isPdf, printPages, releasePages, renderPdf } from './pdf-pages';

type Status = 'loading' | 'pdf' | 'pdf-error' | 'frame' | 'copy' | 'blocked';

interface Block {
  kind: 'h' | 'li' | 'p';
  text: string;
}

/**
 * Shows a link inside the kiosk. PDFs show their pages and a print button, nothing else. Our own
 * pages, and the sites that allow it, open in a frame. The others (most public administration sites) cannot: the viewer shows the saved text
 * of the page when there is one, and a QR code to open the page on a phone.
 */
@Component({
  selector: 'app-link-viewer',
  standalone: true,
  templateUrl: './link-viewer.component.html',
  styleUrls: ['./link-viewer.component.css']
})
export class LinkViewer implements OnDestroy {
  public state = inject(AppStateService);
  public viewer = inject(LinkViewerService);
  private sanitizer = inject(DomSanitizer);

  readonly status = signal<Status>('loading');
  readonly frameUrl = signal<SafeResourceUrl | null>(null);
  // Our own pages and files are trusted; Chrome would not show a PDF in a sandboxed frame.
  readonly sandboxed = signal(true);
  readonly blocks = signal<Block[]>([]);
  readonly qr = signal('');
  readonly pages = signal<string[]>([]);
  readonly printing = signal(false);
  readonly printFailed = signal(false);

  constructor() {
    effect(() => {
      const link = this.viewer.link();
      // Only the link drives this effect, not the signals that show() reads and writes.
      if (link) untracked(() => this.show(link));
    });
  }

  ngOnDestroy(): void {
    releasePages(this.pages());
  }

  async print(): Promise<void> {
    if (this.printing()) return;
    this.printing.set(true);
    this.printFailed.set(false);
    try {
      await printPages(this.pages());
    } catch (err) {
      console.error('Stampa non riuscita:', err);
      this.printFailed.set(true);
    } finally {
      this.printing.set(false);
    }
  }

  private async show(link: ViewerLink): Promise<void> {
    this.status.set('loading');
    this.frameUrl.set(null);
    this.blocks.set([]);
    this.qr.set('');
    this.printFailed.set(false);
    releasePages(this.pages());
    this.pages.set([]);

    if (isPdf(link.url)) {
      const pages = await renderPdf(link.url).catch((err) => {
        console.error('PDF non disponibile:', err);
        return [] as string[];
      });
      if (this.viewer.link() !== link) {
        releasePages(pages);
        return;
      }
      this.pages.set(pages);
      this.status.set(pages.length ? 'pdf' : 'pdf-error');
      return;
    }

    const url = kioskUrl(link.url);
    if (await canFrame(url)) {
      if (this.viewer.link() !== link) return;
      this.sandboxed.set(!isOwn(url));
      this.frameUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(url));
      this.status.set('frame');
      return;
    }

    const [qr, blocks] = await Promise.all([
      QRCode.toDataURL(link.url, { margin: 1, width: 320 }).catch(() => ''),
      link.copy ? loadCopy(link.copy) : Promise.resolve([])
    ]);
    if (this.viewer.link() !== link) return;
    this.qr.set(qr);
    this.blocks.set(blocks);
    this.status.set(blocks.length ? 'copy' : 'blocked');
  }
}

/** Google Maps pages refuse frames, but their "embed" version of the same place is allowed. */
export function kioskUrl(url: string): string {
  try {
    const u = new URL(url);
    if (/(^|\.)google\.[a-z.]+$/.test(u.hostname) && u.pathname.startsWith('/maps')) {
      const place = u.searchParams.get('destination') ?? u.searchParams.get('query');
      if (place) {
        const key = u.searchParams.has('destination') ? 'daddr' : 'q';
        return `https://maps.google.com/maps?${key}=${encodeURIComponent(place)}&output=embed`;
      }
    }
  } catch {
  }
  return url;
}

function isOwn(url: string): boolean {
  return url.startsWith(location.origin + '/') || url.startsWith(API_URL + '/');
}

async function canFrame(url: string): Promise<boolean> {
  if (isOwn(url)) return true;
  try {
    const response = await fetch(`${EMBEDDABLE_API_URL}?url=${encodeURIComponent(url)}`);
    return response.ok && (await response.json()).embeddable === true;
  } catch {
    // Without the backend we cannot know: showing the QR code is safer than a blank frame.
    return false;
  }
}

async function loadCopy(url: string): Promise<Block[]> {
  try {
    const response = await fetch(url);
    return response.ok ? markdownBlocks(await response.text()) : [];
  } catch {
    return [];
  }
}

/** The few Markdown forms used by the saved pages: headings, list items and paragraphs. */
export function markdownBlocks(markdown: string): Block[] {
  const clean = (text: string) => text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*`]+/g, '').trim();
  const blocks: Block[] = [];
  for (const part of markdown.split(/\r?\n\s*\r?\n/)) {
    let current: Block | null = null; // the paragraph or list item that a plain line continues
    for (const line of part.split(/\r?\n/)) {
      const heading = line.match(/^#{1,6}\s+(.*)/);
      const item = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.*)/);
      if (heading) {
        blocks.push({ kind: 'h', text: clean(heading[1]) });
        current = null;
      } else if (item) {
        current = { kind: 'li', text: clean(item[1]) };
        blocks.push(current);
      } else if (!line.trim()) {
        continue;
      } else if (current) {
        current.text += ' ' + clean(line);
      } else {
        current = { kind: 'p', text: clean(line) };
        blocks.push(current);
      }
    }
  }
  return blocks.filter((b) => b.text);
}
