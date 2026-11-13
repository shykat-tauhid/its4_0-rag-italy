import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Chatbot } from './chatbot.component';
import { AppStateService } from '../app-state.service';
import { CHAT_API_URL, CONVERSATION_PDF_API_URL, PRINT_API_URL } from '../api.config';

function streamResponse(events: object[]): Response {
  const body = events.map((e) => JSON.stringify(e) + '\n').join('');
  return new Response(body, { status: 200 });
}

describe('Chatbot', () => {
  let state: AppStateService;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    localStorage.clear();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await TestBed.configureTestingModule({
      imports: [Chatbot],
      providers: [provideHttpClient(), provideHttpClientTesting()]
    }).compileComponents();
    const httpMock = TestBed.inject(HttpTestingController);
    state = TestBed.inject(AppStateService);
    httpMock.expectOne('assets/translation.json').flush({
      it: { chatError: 'Errore di connessione', serviceAnagrafica: 'Anagrafica', chatWelcomeAnagrafica: 'Ciao anagrafe' }
    });
    state.startService('anagrafica');
  });

  afterEach(() => vi.unstubAllGlobals());

  it('invia il messaggio e mostra la risposta del bot in streaming', async () => {
    fetchMock.mockResolvedValue(streamResponse([
      { type: 'token', text: 'Serve il ' },
      { type: 'token', text: 'modulo.' },
      { type: 'sources', sources: [{ number: 1, title: 'Residenza', kind: 'doc', url: null }], forms: [] },
      { type: 'done' }
    ]));
    const fixture = TestBed.createComponent(Chatbot);
    fixture.componentInstance.newMessage.set('  cambio residenza?  ');
    const sending = fixture.componentInstance.sendMessage();
    expect(fixture.componentInstance.waiting()).toBe(true);
    await sending;

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${CHAT_API_URL}/stream`);
    expect(JSON.parse(init.body)).toEqual({
      message: 'cambio residenza?', language: null, service: 'anagrafica', session_id: state.sessionId
    });

    const last = state.chatMessages().at(-1)!;
    expect(last.text).toBe('Serve il modulo.');
    expect(last.sources?.[0].title).toBe('Residenza');
    expect(last.pending).toBe(false);
    expect(state.chatMessages().map((m) => m.text)).toEqual(['Ciao anagrafe', 'cambio residenza?', 'Serve il modulo.']);
    expect(fixture.componentInstance.waiting()).toBe(false);
  });

  it('mostra un errore tradotto se il server non risponde', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const fixture = TestBed.createComponent(Chatbot);
    fixture.componentInstance.newMessage.set('ciao');
    await fixture.componentInstance.sendMessage();
    expect(state.chatMessages().at(-1)).toEqual({ text: 'Errore di connessione', sender: 'bot', pending: false });
  });

  it('ignora i messaggi vuoti', async () => {
    const fixture = TestBed.createComponent(Chatbot);
    fixture.componentInstance.newMessage.set('   ');
    await fixture.componentInstance.sendMessage();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("non stampa finché l'utente non ha scritto nulla", async () => {
    const fixture = TestBed.createComponent(Chatbot);
    expect(fixture.componentInstance.canPrint()).toBe(false);
    await fixture.componentInstance.printConversation();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('stampa la conversazione senza il messaggio di benvenuto', async () => {
    state.addMessage({ text: 'cambio residenza?', sender: 'user' });
    state.addMessage({ text: 'Serve il modulo.', sender: 'bot' });
    fetchMock.mockImplementation(async (url: string) => {
      if (url === CONVERSATION_PDF_API_URL) return new Response(new Uint8Array([37, 80, 68, 70]));
      if (url === 'blob:pagina-1') return new Response(new Blob(['png'], { type: 'image/png' }));
      return new Response(null, { status: 204 });
    });
    const fixture = TestBed.createComponent(Chatbot);
    fixture.componentInstance.pdf.render = async () => ['blob:pagina-1'];
    fixture.componentInstance.pdf.release = () => {};
    await fixture.componentInstance.printConversation();

    const pdfCall = fetchMock.mock.calls.find(([url]) => url === CONVERSATION_PDF_API_URL)!;
    expect(JSON.parse(pdfCall[1].body)).toEqual({
      messages: [
        { role: 'user', content: 'cambio residenza?' },
        { role: 'assistant', content: 'Serve il modulo.' }
      ]
    });
    const printCall = fetchMock.mock.calls.find(([url]) => url === PRINT_API_URL)!;
    expect(JSON.parse(printCall[1].body).pages).toHaveLength(1);
    expect(fixture.componentInstance.printStatus()).toBe('done');
  });

  it("segnala l'errore se la stampante non risponde", async () => {
    state.addMessage({ text: 'ciao', sender: 'user' });
    fetchMock.mockImplementation(async (url: string) => {
      if (url === CONVERSATION_PDF_API_URL) return new Response(new Uint8Array([37, 80, 68, 70]));
      if (url === 'blob:pagina-1') return new Response(new Blob(['png']));
      return new Response(null, { status: 503 });
    });
    const fixture = TestBed.createComponent(Chatbot);
    fixture.componentInstance.pdf.render = async () => ['blob:pagina-1'];
    fixture.componentInstance.pdf.release = () => {};
    await fixture.componentInstance.printConversation();
    expect(fixture.componentInstance.printStatus()).toBe('error');
  });
});
