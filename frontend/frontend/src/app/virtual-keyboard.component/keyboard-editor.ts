import { Candidate } from './pinyin-ime';

export interface EditorState {
  text: string;
  caret: number;
  composition: string;
}

export interface EditorOptions {
  ime?: boolean;
  punctuation?: Record<string, string>;
  firstCandidate?: (composition: string) => Candidate | null;
}

export function emptyEditor(text = ''): EditorState {
  return { text, caret: text.length, composition: '' };
}

export function isControlKey(button: string): boolean {
  return /^\{.+\}$/.test(button);
}

export function pressKey(state: EditorState, button: string, options: EditorOptions = {}): EditorState {
  if (button === '{bksp}') return backspace(state);
  if (button === '{space}') return typeSpace(state, options);
  if (isControlKey(button)) return state;

  if (options.ime && state.composition !== '' && button === "'") {
    return state.composition.endsWith("'") ? state : { ...state, composition: state.composition + button };
  }
  if (options.ime && /^[a-z]$/.test(button)) {
    return { ...state, composition: state.composition + button };
  }

  const next = commitComposition(state, options);
  const char = options.ime ? options.punctuation?.[button] ?? button : button;
  return insert(next, char);
}

export function pickCandidate(state: EditorState, candidate: Candidate): EditorState {
  const rest = state.composition.slice(candidate.consumed).replace(/^'+/, '');
  return insert({ ...state, composition: rest }, candidate.word);
}

export function commitRaw(state: EditorState): EditorState {
  if (state.composition === '') return state;
  return insert({ ...state, composition: '' }, state.composition.replace(/'/g, ''));
}

function commitComposition(state: EditorState, options: EditorOptions): EditorState {
  let next = state;
  while (next.composition !== '') {
    const candidate = options.firstCandidate?.(next.composition);
    if (!candidate || candidate.consumed <= 0) return commitRaw(next);
    next = pickCandidate(next, candidate);
  }
  return next;
}

function typeSpace(state: EditorState, options: EditorOptions): EditorState {
  if (state.composition === '') return insert(state, ' ');
  const candidate = options.firstCandidate?.(state.composition);
  return candidate ? pickCandidate(state, candidate) : commitRaw(state);
}

function backspace(state: EditorState): EditorState {
  if (state.composition !== '') return { ...state, composition: state.composition.slice(0, -1) };
  if (state.caret === 0) return state;
  const before = Array.from(state.text.slice(0, state.caret));
  before.pop();
  const head = before.join('');
  return { ...state, text: head + state.text.slice(state.caret), caret: head.length };
}

function insert(state: EditorState, value: string): EditorState {
  const head = state.text.slice(0, state.caret) + value;
  return { ...state, text: head + state.text.slice(state.caret), caret: head.length };
}
