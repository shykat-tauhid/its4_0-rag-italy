import { keyboardConfig } from './keyboard-layouts';

describe('keyboardConfig', () => {
  it('italiano: tastiera italiana, senza Tab e con il tasto chiudi', () => {
    const it = keyboardConfig('it', false);
    expect(it.layout['default'].join(' ')).toContain('ò à ù');
    expect(it.layout['default'].join(' ')).not.toContain('{tab}');
    expect(it.layout['default'].at(-1)).toContain('{close}');
    expect(it.switchLabel).toBeNull();
    expect(it.ime).toBeNull();
  });

  it('ucraino: tastiera cirillica ucraina con il tasto ABC', () => {
    const uk = keyboardConfig('uk', false);
    expect(uk.layout['default'].join(' ')).toContain('й ц у к е н г ш щ з х ї ґ');
    expect(uk.layout['default'].join(' ')).toContain('і');
    expect(uk.layout['default'].join(' ')).toContain('є');
    expect(uk.switchLabel).toBe('ABC');
    expect(keyboardConfig('uk', true).layout['default'].join(' ')).toContain('q w e r t y');
    expect(keyboardConfig('uk', true).switchLabel).toBe('АБВ');
  });

  it('cinese: pinyin su QWERTY con la punteggiatura cinese', () => {
    const zh = keyboardConfig('zh', false);
    expect(zh.ime).toBe('pinyin');
    expect(zh.layout['default'].join(' ')).toContain('q w e r t y');
    expect(zh.layout['default'].join(' ')).toContain(',');
    expect(zh.punctuation[',']).toBe('，');
    expect(zh.switchLabel).toBe('ABC');
    expect(keyboardConfig('zh', true).ime).toBeNull();
  });

  it('bengali: tastiera bengali con i segni leggibili e il tasto ABC', () => {
    const bn = keyboardConfig('bn', false);
    expect(bn.layout['default'].join(' ')).toContain('ক গ ঙ');
    expect(bn.layout['shift'].join(' ')).toContain('আ');
    expect(bn.display['‌']).toBe('ZWNJ');
    expect(bn.display['্']).toBe('◌্');
    expect(bn.switchLabel).toBe('ABC');
    expect(keyboardConfig('bn', true).layout['default'].join(' ')).toContain('q w e r t y');
  });

  it('filippino: QWERTY con la ñ', () => {
    const tl = keyboardConfig('tl', false);
    expect(tl.layout['default'].join(' ')).toContain('l ñ');
    expect(tl.layout['shift'].join(' ')).toContain('L Ñ');
    expect(tl.switchLabel).toBeNull();
  });

  it('arabo: da destra a sinistra, diacritici visibili, può passare alle lettere latine', () => {
    const ar = keyboardConfig('ar', false);
    expect(ar.rtl).toBe(true);
    expect(ar.switchLabel).toBe('ABC');
    expect(ar.layout['default'].at(-1)!.startsWith('{abc}')).toBe(true);
    expect(ar.layout['default'].join(' ')).toContain('لا');
    expect(ar.display['َ']).toBe('◌َ');

    const arLatin = keyboardConfig('ar', true);
    expect(arLatin.rtl).toBe(false);
    expect(arLatin.layout['default'].join(' ')).toContain('q w e r t y');
  });

  it('lingua sconosciuta → italiano', () => {
    expect(keyboardConfig(null, false).layout['default'].join(' ')).toContain('ò à ù');
  });
});
