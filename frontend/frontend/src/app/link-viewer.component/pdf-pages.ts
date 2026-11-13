// PDFs are shown as page images, not in the browser's PDF viewer: on the kiosk there must be
// nothing to zoom, download or change, only the pages to scroll and a button to print them.

import { API_URL, PDF_API_URL, PRINT_API_URL } from '../api.config';

// About 180 dpi (PDF units are 1/72 inch): sharp on screen and good enough on paper.
const SCALE = 2.5;

export function isPdf(url: string): boolean {
  try {
    return new URL(url, location.href).pathname.toLowerCase().endsWith('.pdf');
  } catch {
    return false;
  }
}

// pdf.js runs its parser here, not in a separate worker: when globalThis.pdfjsWorker is set it
// uses it directly, so no worker file has to be served. The forms are a few pages each.
async function loadPdfjs() {
  const [pdfjs, worker] = await Promise.all([
    import('pdfjs-dist'),
    // @ts-expect-error: the worker module has no type declarations.
    import('pdfjs-dist/build/pdf.worker.min.mjs')
  ]);
  (globalThis as { pdfjsWorker?: unknown }).pdfjsWorker = worker;
  return pdfjs;
}

/** The pages of the PDF at url as image URLs (to release with releasePages). */
export async function renderPdf(url: string): Promise<string[]> {
  // Other sites do not let the browser read their files: the backend downloads them for us.
  const own = url.startsWith(location.origin + '/') || url.startsWith(API_URL + '/');
  const response = await fetch(own ? url : `${PDF_API_URL}?url=${encodeURIComponent(url)}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return renderPdfData(await response.arrayBuffer());
}

/** The pages of a PDF already downloaded, as image URLs (to release with releasePages). */
export async function renderPdfData(data: ArrayBuffer): Promise<string[]> {
  const pdfjs = await loadPdfjs();
  const pdf = await pdfjs.getDocument({ data: new Uint8Array(data) }).promise;
  try {
    const pages: string[] = [];
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n);
      const viewport = page.getViewport({ scale: SCALE });
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      const context = canvas.getContext('2d')!;
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      await page.render({ canvasContext: context, viewport }).promise;
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
      if (blob) pages.push(URL.createObjectURL(blob));
    }
    return pages;
  } finally {
    await pdf.destroy();
  }
}

export function releasePages(pages: string[]): void {
  pages.forEach((page) => URL.revokeObjectURL(page));
}

/**
 * Prints the pages, one per sheet, on the kiosk's Bluetooth printer: the backend sends them to
 * it directly, without any print dialog. Rejects when the printer cannot be reached.
 */
export async function printPages(pages: string[]): Promise<void> {
  const images = await Promise.all(pages.map(dataUrl));
  const response = await fetch(PRINT_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages: images })
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
}

async function dataUrl(url: string): Promise<string> {
  const blob = await (await fetch(url)).blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
