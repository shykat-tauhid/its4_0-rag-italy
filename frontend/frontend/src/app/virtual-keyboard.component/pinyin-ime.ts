export interface Candidate {
  word: string;
  consumed: number;
}

interface Entry {
  word: string;
  syllables: string[];
  rank: number;
  cost: number;
}

interface Scored extends Candidate {
  group: number;
  rank: number;
}

const NONE = 0;
const ABBREVIATED = 1;
const EXACT = 2;

export class PinyinIme {
  private readonly byInitial = new Map<string, Entry[]>();

  constructor(dictionary: string) {
    const rows = dictionary
      .split('\n')
      .map((line) => line.trim().split(' '))
      .filter(([word, pinyin]) => word && pinyin);
    const total = rows.reduce((sum, [, , freq]) => sum + (Number(freq) || 1), 0);

    rows.forEach(([word, pinyin, freq], rank) => {
      const entry = { word, syllables: pinyin.split("'"), rank, cost: Math.log(total / (Number(freq) || 1)) };
      const initial = pinyin[0];
      const list = this.byInitial.get(initial);
      if (list) list.push(entry);
      else this.byInitial.set(initial, [entry]);
    });
  }

  candidates(composition: string, limit = 60): Candidate[] {
    const { letters, boundaries, rawIndex } = splitComposition(composition);
    if (!letters) return [];

    const scored: Scored[] = [];
    for (const entry of this.byInitial.get(letters[0]) ?? []) {
      if (entry.syllables.length > letters.length) continue;
      const full = matchFull(entry.syllables, letters, boundaries);
      if (full !== NONE) {
        scored.push({ word: entry.word, consumed: composition.length, group: full === EXACT ? 0 : 1, rank: entry.rank });
        continue;
      }
      const partial = matchPartial(entry.syllables, letters, boundaries);
      if (partial > 0) {
        scored.push({ word: entry.word, consumed: rawIndex[partial], group: 2, rank: entry.rank - partial * 1e6 });
      }
    }

    scored.sort((a, b) => a.group - b.group || a.rank - b.rank);

    const sentence = this.sentence(letters, boundaries);
    if (sentence) {
      const exact = scored.filter((s) => s.group === 0).length;
      scored.splice(exact, 0, { word: sentence, consumed: composition.length, group: 0, rank: -1 });
    }

    const seen = new Set<string>();
    const result: Candidate[] = [];
    for (const { word, consumed } of scored) {
      const key = `${word}|${consumed}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({ word, consumed });
      if (result.length >= limit) break;
    }
    return result;
  }

  private sentence(letters: string, boundaries: Set<number>): string | null {
    const best: { cost: number; from: number; word: string }[] = [{ cost: 0, from: -1, word: '' }];
    for (let pos = 0; pos < letters.length; pos++) {
      const here = best[pos];
      if (!here) continue;
      for (const entry of this.byInitial.get(letters[pos]) ?? []) {
        if (entry.syllables.some((s) => VOWELLESS.test(s))) continue;
        const end = matchWord(entry.syllables, letters, pos, boundaries);
        if (end < 0) continue;
        const cost = here.cost + entry.cost;
        if (!best[end] || cost < best[end].cost) best[end] = { cost, from: pos, word: entry.word };
      }
    }

    const words: string[] = [];
    for (let pos = letters.length; pos > 0; pos = best[pos].from) {
      if (!best[pos]) return null;
      words.unshift(best[pos].word);
    }
    return words.length > 1 ? words.join('') : null;
  }
}

const VOWELLESS = /^(n|m|ng|hm|hng)$/;

function matchWord(syllables: string[], letters: string, start: number, boundaries: Set<number>): number {
  let pos = start;
  for (let i = 0; i < syllables.length; i++) {
    const syllable = syllables[i];
    const last = i === syllables.length - 1;
    const available = letters.length - pos;
    if (letters.startsWith(syllable, pos)) {
      if (crossesBoundary(pos, pos + syllable.length, boundaries)) return -1;
      pos += syllable.length;
    } else if (last && available > 0 && available < syllable.length && syllable.startsWith(letters.slice(pos))) {
      if (crossesBoundary(pos, letters.length, boundaries)) return -1;
      pos = letters.length;
    } else {
      return -1;
    }
  }
  return pos;
}

function splitComposition(composition: string) {
  let letters = '';
  const boundaries = new Set<number>();
  const rawIndex: number[] = [];
  for (let i = 0; i < composition.length; i++) {
    if (composition[i] === "'") {
      boundaries.add(letters.length);
    } else {
      rawIndex[letters.length] = i;
      letters += composition[i];
    }
  }
  rawIndex[letters.length] = composition.length;
  return { letters, boundaries, rawIndex };
}

function crossesBoundary(start: number, end: number, boundaries: Set<number>): boolean {
  for (let i = start + 1; i < end; i++) {
    if (boundaries.has(i)) return true;
  }
  return false;
}

function matchFull(syllables: string[], letters: string, boundaries: Set<number>): number {
  const go = (index: number, pos: number): number => {
    if (index === syllables.length) return pos === letters.length ? EXACT : NONE;
    const syllable = syllables[index];
    let best = NONE;
    for (let len = 1; len <= syllable.length && pos + len <= letters.length; len++) {
      if (letters[pos + len - 1] !== syllable[len - 1]) break;
      if (crossesBoundary(pos, pos + len, boundaries)) break;
      const rest = go(index + 1, pos + len);
      if (rest === NONE) continue;
      best = Math.max(best, len === syllable.length ? rest : ABBREVIATED);
      if (best === EXACT) return EXACT;
    }
    return best;
  };
  return go(0, 0);
}

function matchPartial(syllables: string[], letters: string, boundaries: Set<number>): number {
  let pos = 0;
  for (const syllable of syllables) {
    if (!letters.startsWith(syllable, pos) || crossesBoundary(pos, pos + syllable.length, boundaries)) return 0;
    pos += syllable.length;
  }
  return pos < letters.length ? pos : 0;
}

let loading: Promise<PinyinIme> | null = null;

export function loadPinyinIme(url = 'ime/zh-pinyin.txt'): Promise<PinyinIme> {
  loading ??= fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.text();
    })
    .then((text) => new PinyinIme(text))
    .catch((err) => {
      loading = null;
      throw err;
    });
  return loading;
}
