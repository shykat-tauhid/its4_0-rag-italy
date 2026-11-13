import { TestBed } from '@angular/core/testing';
import { A11Y_STORAGE_KEY, AccessibilityService } from './accessibility.service';

describe('AccessibilityService', () => {
  let service: AccessibilityService;
  const root = document.documentElement;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(AccessibilityService);
    TestBed.tick();
  });

  it('applica i valori di default alla radice', () => {
    expect(root.style.getPropertyValue('--font-scale')).toBe('1');
    expect(root.dataset['cvd']).toBe('none');
    expect(root.dataset['font']).toBe('default');
    expect(['light', 'dark']).toContain(root.dataset['theme']);
  });

  it('ingrandisce e riduce il testo entro i limiti', () => {
    for (let i = 0; i < 20; i++) service.increaseText();
    expect(service.prefs().fs).toBe(200);
    for (let i = 0; i < 20; i++) service.decreaseText();
    expect(service.prefs().fs).toBe(85);
    TestBed.tick();
    expect(root.style.getPropertyValue('--font-scale')).toBe('0.85');
  });

  it('cambia colori, carattere, tema e opzioni, poi ripristina', () => {
    service.set('cvd', 'deutan');
    service.set('font', 'dyslexic');
    service.set('theme', 'dark');
    service.toggle('motion');
    service.toggle('links');
    TestBed.tick();
    expect(root.dataset['cvd']).toBe('deutan');
    expect(root.dataset['font']).toBe('dyslexic');
    expect(root.dataset['theme']).toBe('dark');
    expect(root.dataset['motion']).toBe('1');
    expect(root.dataset['links']).toBe('1');
    expect(root.dataset['spacing']).toBe('0');

    service.reset();
    TestBed.tick();
    expect(root.dataset['cvd']).toBe('none');
    expect(root.dataset['motion']).toBe('0');
    expect(service.prefs().fs).toBe(100);
  });

  it('salva le preferenze nello stesso formato della web app', () => {
    service.set('cvd', 'contrast');
    service.increaseText();
    TestBed.tick();
    expect(JSON.parse(localStorage.getItem(A11Y_STORAGE_KEY)!)).toEqual({
      fs: 115, font: 'default', cvd: 'contrast', theme: 'auto', spacing: false, links: false, motion: false
    });
  });
});
