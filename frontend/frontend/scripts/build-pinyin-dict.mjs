import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const [source, target = 'public/ime/zh-pinyin.txt'] = process.argv.slice(2);
if (!source) {
  console.error('Uso: node scripts/build-pinyin-dict.mjs <rawdict_utf16_65105_freq.txt> [output]');
  console.error('Sorgente: https://android.googlesource.com/platform/packages/inputmethods/PinyinIME/+/refs/heads/main/jni/data/');
  process.exit(1);
}

const HAN = /^\p{Script=Han}+$/u;
const SYLLABLE = /^[a-z]+$/;

const entries = readFileSync(source, 'utf16le')
  .replace(/^﻿/, '')
  .split(/\r?\n/)
  .map((line) => line.trim().split(/\s+/))
  .filter(([word, freq, rare, ...syllables]) =>
    word && HAN.test(word) && rare === '0' && Number(freq) >= 1 && syllables.length === [...word].length && syllables.every((s) => SYLLABLE.test(s))
  )
  .map(([word, freq, , ...syllables]) => ({ word, freq: Math.round(Number(freq)), pinyin: syllables.join("'") }))
  .sort((a, b) => b.freq - a.freq);

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, entries.map((e) => `${e.word} ${e.pinyin} ${e.freq}`).join('\n') + '\n');
console.log(`${entries.length} voci scritte in ${target}`);
