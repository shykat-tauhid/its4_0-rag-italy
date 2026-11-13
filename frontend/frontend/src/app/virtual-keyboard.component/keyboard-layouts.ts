import italian from 'simple-keyboard-layouts/build/layouts/italian';
import english from 'simple-keyboard-layouts/build/layouts/english';
import arabic from 'simple-keyboard-layouts/build/layouts/arabic';
import ukrainian from 'simple-keyboard-layouts/build/layouts/ukrainian';
import bengali from 'simple-keyboard-layouts/build/layouts/bengali';

type Layout = Record<string, string[]>;

interface LayoutItem {
  layout: Layout;
}

const filipino: LayoutItem = {
  layout: {
    default: english.layout['default'].map((row) => row.replace(' l ;', ' l ñ ;')),
    shift: english.layout['shift'].map((row) => row.replace(' L :', ' L Ñ :'))
  }
};

const LAYOUTS: Record<string, LayoutItem> = {
  it: italian,
  uk: ukrainian,
  zh: english,
  bn: bengali,
  tl: filipino,
  ar: arabic
};

const ZH_PUNCTUATION: Record<string, string> = {
  ',': '，',
  '.': '。',
  '?': '？',
  '!': '！',
  ';': '；',
  ':': '：',
  '(': '（',
  ')': '）'
};

const NATIVE_LABEL: Record<string, string> = {
  uk: 'АБВ',
  zh: '中',
  bn: 'অআ',
  ar: 'أبج'
};

const BASE_DISPLAY: Record<string, string> = {
  '{bksp}': '⌫',
  '{enter}': '↵',
  '{shift}': '⇧',
  '{lock}': '⇪',
  '{space}': ' ',
  '{close}': '⌨ ✕',
  '‌': 'ZWNJ',
  '‍': 'ZWJ'
};

export interface KeyboardConfig {
  layout: Layout;
  display: Record<string, string>;
  ime: 'pinyin' | null;
  punctuation: Record<string, string>;
  rtl: boolean;
  switchLabel: string | null;
}

export function keyboardConfig(lang: string | null, latin: boolean): KeyboardConfig {
  const code = lang && LAYOUTS[lang] ? lang : 'it';
  const nonLatin = code in NATIVE_LABEL;
  const useLatin = nonLatin && latin;
  const item: LayoutItem = useLatin ? english : LAYOUTS[code];
  const switchLabel = nonLatin ? (useLatin ? NATIVE_LABEL[code] : 'ABC') : null;

  const layout: Layout = {};
  for (const [name, rows] of Object.entries(item.layout)) {
    const cleaned = rows.map((row) => row.split(' ').filter((key) => key !== '{tab}').join(' '));
    const last = cleaned.pop()!.split(' ').filter((key) => key !== '{space}');
    layout[name] = [...cleaned, [nonLatin ? '{abc}' : '', ...last, '{space}', '{close}'].filter(Boolean).join(' ')];
  }

  const display: Record<string, string> = { ...BASE_DISPLAY, '{abc}': switchLabel ?? '' };
  for (const rows of Object.values(layout)) {
    for (const key of rows.join(' ').split(' ')) {
      if (/^\p{M}+$/u.test(key)) display[key] = `◌${key}`;
    }
  }

  const ime = code === 'zh' && !useLatin ? 'pinyin' : null;
  return {
    layout,
    display,
    ime,
    punctuation: ime ? ZH_PUNCTUATION : {},
    rtl: code === 'ar' && !useLatin,
    switchLabel
  };
}
