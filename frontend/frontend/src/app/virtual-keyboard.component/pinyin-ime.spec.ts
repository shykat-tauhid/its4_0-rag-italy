import dictionary from '../../../public/ime/zh-pinyin.txt' with { loader: 'text' };
import { PinyinIme } from './pinyin-ime';

describe('PinyinIme con il dizionario vero', () => {
  const ime = new PinyinIme(dictionary);
  const words = (input: string, limit = 10) => ime.candidates(input, limit).map((c) => c.word);

  it('propone parole intere dal pinyin completo', () => {
    expect(words('nihao', 3)).toContain('你好');
    expect(words('xiexie', 3)).toContain('谢谢');
    expect(words('zhongguo', 3)).toContain('中国');
    expect(words('shenfenzheng', 3)).toContain('身份证');
    expect(words('yinhang', 3)).toContain('银行');
  });

  it('accetta il pinyin abbreviato o non finito', () => {
    expect(words('zhongg', 5)).toContain('中国');
    expect(words('sfz', 5)).toContain('身份证');
    expect(words('nih', 10)).toContain('你好');
  });

  it('una sillaba propone i caratteri più comuni', () => {
    expect(words('wo', 5)).toContain('我');
    expect(words('de', 5)).toContain('的');
    expect(words('nv', 5)).toContain('女');
  });

  it('compone la frase intera come primo suggerimento', () => {
    expect(words('nihaoma', 1)).toEqual(['你好吗']);
    expect(words('woxiangzufang', 1)).toEqual(['我想租房']);
    expect(words('woyaobanshenfenzheng', 1)).toEqual(['我要办身份证']);
    expect(words('qingwenzenmebanjuzhuzheng', 1)).toEqual(['请问怎么办居住证']);
    expect(words('nh', 1)).toEqual(['你好']);
  });

  it('se la frase non è nel dizionario propone la parte iniziale', () => {
    const candidates = ime.candidates('nihaoma');
    const hello = candidates.find((c) => c.word === '你好');
    expect(hello?.consumed).toBe(5);
    expect(ime.candidates("xi'an", 5).map((c) => c.word)).toContain('西安');
  });

  it('è abbastanza veloce per ogni tasto', () => {
    const start = performance.now();
    for (const input of ['z', 'zh', 'zho', 'zhon', 'zhong', 'zhongg', 'zhonggu', 'zhongguo', 'shenfenzhengming']) {
      ime.candidates(input);
    }
    expect(performance.now() - start).toBeLessThan(500);
  });
});
