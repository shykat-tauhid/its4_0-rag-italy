import { EditorOptions, EditorState, commitRaw, emptyEditor, pickCandidate, pressKey } from './keyboard-editor';
import { keyboardConfig } from './keyboard-layouts';
import { PinyinIme } from './pinyin-ime';

function type(keys: string[], options: EditorOptions = {}, start: EditorState = emptyEditor()): EditorState {
  return keys.reduce((state, key) => pressKey(state, key, options), start);
}

describe('pressKey', () => {
  it('scrive e cancella nella posizione del cursore', () => {
    let state = type(['c', 'a', 'o']);
    state = { ...state, caret: 2 };
    state = pressKey(state, 'i');
    expect(state.text).toBe('caio');
    expect(state.caret).toBe(3);
    state = pressKey(state, '{bksp}');
    expect(state.text).toBe('cao');
    expect(type(['{space}', 'x']).text).toBe(' x');
    expect(type(['{shift}', '{abc}', 'a']).text).toBe('a');
  });

  it('italiano, ucraino, arabo, bengali e filippino scrivono le loro lettere', () => {
    expect(type(['p', 'e', 'r', 'c', 'h', 'é']).text).toBe('perché');
    expect(type(['п', 'р', 'и', 'в', 'і', 'т']).text).toBe('привіт');
    expect(type(['م', 'ر', 'ح', 'ب', 'ا']).text).toBe('مرحبا');
    expect(type(['ل', 'ا', '{space}', 'لا']).text).toBe('لا لا');
    expect(type(['ক', 'ি', 'ন', '্', 'ত', 'ু']).text).toBe('কিন্তু');
    expect(type(['S', 'e', 'ñ', 'o', 'r']).text).toBe('Señor');
  });

  it('cancella toglie un solo segno anche in bengali e arabo', () => {
    expect(type(['ক', 'ি', '{bksp}']).text).toBe('ক');
    expect(type(['ب', 'َ', '{bksp}']).text).toBe('ب');
    expect(type(['{bksp}']).text).toBe('');
  });
});

describe('pinyin', () => {
  const ime = new PinyinIme(['你 ni', '好 hao', "你好 ni'hao", '吗 ma', "中国 zhong'guo", '中 zhong'].join('\n'));
  const config = keyboardConfig('zh', false);
  const options: EditorOptions = {
    ime: true,
    punctuation: config.punctuation,
    firstCandidate: (composition) => ime.candidates(composition, 1)[0] ?? null
  };

  it('le lettere restano in composizione finché non scegli', () => {
    const state = type(['n', 'i', 'h', 'a', 'o'], options);
    expect(state.text).toBe('');
    expect(state.composition).toBe('nihao');
  });

  it('spazio inserisce la frase composta', () => {
    const state = pressKey(type(['n', 'i', 'h', 'a', 'o', 'm', 'a'], options), '{space}', options);
    expect(state.text).toBe('你好吗');
    expect(state.composition).toBe('');
  });

  it('scegliendo una parola parziale il resto rimane in composizione', () => {
    let state = type(['n', 'i', 'h', 'a', 'o', 'm', 'a'], options);
    const hello = ime.candidates(state.composition).find((c) => c.word === '你好')!;
    state = pickCandidate(state, hello);
    expect(state.text).toBe('你好');
    expect(state.composition).toBe('ma');
    state = pressKey(state, '{space}', options);
    expect(state.text).toBe('你好吗');
  });

  it('toccare una parola la inserisce', () => {
    const state = type(['z', 'g'], options);
    const [first] = ime.candidates(state.composition);
    expect(first.word).toBe('中国');
    expect(pickCandidate(state, first).text).toBe('中国');
  });

  it('la punteggiatura conferma la parola e diventa cinese', () => {
    expect(type(['n', 'i', 'h', 'a', 'o', ',', '?'], options).text).toBe('你好，？');
  });

  it('cancella toglie prima le lettere in composizione', () => {
    const state = type(['n', 'i', '{bksp}'], options, emptyEditor('好'));
    expect(state.text).toBe('好');
    expect(state.composition).toBe('n');
  });

  it('invio lascia le lettere latine', () => {
    const state = commitRaw(type(['o', 'k'], options));
    expect(state.text).toBe('ok');
    expect(state.composition).toBe('');
  });
});
