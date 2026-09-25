# Chinese Pinyin Conversion Library

Implement, in **TypeScript**, the algorithmic core of a library that converts Chinese text to **pinyin**
(the romanization of Mandarin). The character/phrase **dictionaries are provided** for you — you
implement the conversion, analysis, segmentation, and matching **logic** on top of them.

## Working directory & deliverables

Work in the **current working directory** (the project root — the directory these instructions are in).
One thing is already present and **must not be modified or recreated** — import from it:

- `lib/data/` — the pinyin character/phrase dictionaries plus the surname and tone-sandhi tables.

Everything else is yours to implement, including any shared constants/enums your code needs (e.g. the
surrogate-pair detection regexes and any segmentation priority/probability values) — the standard
Unicode surrogate ranges and your own weighting constants are fine; no test distinguishes specific
constant values.

Modules resolve the alias **`@/*` → `lib/*`**, so you read the provided data the way the rest of the
library does, e.g. `import DICT1 from '@/data/dict1'`. Organise your own source however you like; the
only fixed entry point is **`lib/index.ts`**, which must re-export the public API listed below.

There is **no build step**: the grading harness runs your TypeScript source directly. **Do NOT clone,
download, or `npm install` anything** — the environment is offline, the library has no runtime
dependencies, and the data is already provided. Implement the behavior yourself.

## Public API

`lib/index.ts` must export the following names (organise the implementation behind them freely):

`pinyin`, `match`, `segment`, `OutputFormat`, `polyphonic`, `addDict`, `getInitialAndFinal`,
`getFinalParts`, `getNumOfTone`.

### `pinyin(text, options?)`

Converts Chinese text to pinyin. Returns a space-separated string by default. Options:

| Option | Values | Meaning |
|--------|--------|---------|
| `toneType` | `'symbol'` (default) / `'num'` / `'none'` | tone as a diacritic (`hǎo`), a trailing number (`hao3`), or omitted (`hao`) |
| `pattern` | `'pinyin'` (default) / `'initial'` / `'final'` / `'num'` / `'first'` / `'finalHead'` / `'finalBody'` / `'finalTail'` | which part of each syllable to output (num = tone number; first = first letter; final split into head/body/tail) |
| `type` | `'string'` (default) / `'array'` | return a joined string or an array of per-character results |
| `v` | boolean | render the vowel `ü` as the letter `v` where `ü` appears as a plain letter (i.e. under `toneType: 'num'`/`'none'`; with the default tone diacritic the mark stays on `ü`) |
| `nonZh` | `'spaced'` (default) / `'consecutive'` / `'removed'` | non-Chinese runs kept space-separated, kept as-is (consecutive), or removed |
| `multiple` | boolean | for a **single** Chinese character, return all of its readings |
| `mode` | `'normal'` (default) / `'surname'` | prefer surname readings for characters in the surname table |
| `surname` | `'off'` / `'all'` / `'head'` | scope of surname matching. Defaults to `off`, except it defaults to `all` when `mode:'surname'`. Setting `surname` explicitly to `all` or `head` **enables** surname matching on its own, even without `mode:'surname'`; `head` = only a leading surname |
| `toneSandhi` | boolean (default `true`) | apply 一/不 tone sandhi (see "Behaviors") |
| `segmentit` | `1` / `2` / `3` (default `2`) | word-segmentation algorithm used to pick contextual readings: `1` reverse-maximum-match, `2` maximum-probability, `3` minimum-tokenization |

### `match(text, pinyinQuery, options?)`

Fuzzy-search `text` by a pinyin `query`; returns the array of matched **indices** into `text`, or
**`null`** when the whole query cannot be matched. The query is consumed left-to-right, assigning
successive (not necessarily adjacent) characters of `text` to successive pieces of the query so that
each assigned character satisfies the applicable precision against one of its readings; a match
succeeds iff some such assignment consumes the entire query. Indices are **0-based UTF-16 code-unit
offsets** into `text`, so a surrogate-pair (astral / "double-unicode") character occupies **two**
index positions and a matched surrogate-pair character contributes both of its offsets to the result.
A **non-Chinese** character in `text` matches only by being typed literally in the query.

Options:

- `precision` (default `'first'`) — how much of a character's pinyin each query piece must cover:
  - `'first'` = the pinyin's **first letter, or its whole pinyin** — a character matches when the
    current query letter equals its first letter, *or* when the query continues with the character's
    **entire** pinyin (nothing in between). So under the default a query may freely mix single
    initials and full syllables: `match('汉语拼音', 'hy')` → `[0, 1]` (matched by first letters
    `h`, `y`), while `match('中国人民', 'zhongren')` → `[0, 2]` (中 matched by its full `zhong`, 人
    by its full `ren`, 国 skipped).
  - `'start'` = **any** leading prefix of the pinyin (one letter up to the whole syllable) — unlike
    `'first'` this also admits a partial prefix such as `sh` of `shi`.
  - `'every'` = the whole pinyin.
  - `'any'` = any contiguous substring of the pinyin.
- `lastPrecision` (default `'start'`) — the precision applied to the **last** matched character only
  (the earlier characters use `precision`). Setting `precision: 'any'` also forces `lastPrecision` to
  `'any'`.
- `continuous` (boolean, default `false`) — when `true`, matched characters must be adjacent; when
  `false`, unmatched characters between matches may be skipped.
- `space` (default `'ignore'`) — `'ignore'` strips spaces from the query before matching; `'preserve'`
  requires a query space to line up with a space in `text`, and that space's index is included in the
  result.
- `insensitive` (boolean, default `true`) — case-insensitive matching.
- `v` (boolean) — accept `v` in the query for `ü`.

### `segment(text, options?)`

Word-segment `text` and attach pinyin. `options.format` is an `OutputFormat` enum value; the enum must
provide these members: `AllSegment` (default), `AllArray`, `AllString`, `PinyinSegment`, `PinyinArray`,
`PinyinString`, `ZhSegment`, `ZhArray`, `ZhString`.

- `*Segment` forms return an array of per-word entries; `Pinyin*` forms carry only pinyin, `Zh*` forms
  only the Chinese, `All*` forms carry both as `{ origin, result }`.
- `*Array` forms break each word into per-character items; `*String` forms concatenate a word's own
  syllables with **no** separator and join the resulting words with `separator`.
- A **non-Chinese** character (punctuation, Latin letters, digits, etc.) has no pinyin to convert, so it
  stands alone as its own word and is carried through **literally** in every output form: both its `Zh*`
  value and its `Pinyin*` value are the character itself (never empty). It therefore appears as a literal
  `*String` token (joined by `separator`) and as a single-element `*Array` word — consistent with
  `pinyin()`'s default `nonZh:'spaced'`, which keeps rather than drops non-Chinese runs.
- Also accepts `separator` (word separator for the `*String` forms, default `' '`), `mode: 'surname'`,
  and `segmentit` (default `2`, maximum-probability).
- Non-string input is returned unchanged.

Words are grouped by consulting the loaded phrase dictionary: consecutive characters that form a
multi-character entry in the dictionary are grouped into one word, and characters with no such entry
stand alone. Load the full phrase dictionary via `addDict` (see below) so these multi-character
words can be recognised.

### `polyphonic(text, options?)`

Return **all** readings of each character. By default, an array with one entry per character, each a
space-joined string of that character's readings. Readings that become **identical after the requested
`toneType`/`pattern` transform are de-duplicated** per character — e.g. two readings of a character
that differ only in tone collapse to a single entry under `toneType: 'none'`, but stay separate under
`toneType: 'num'` because the two strings still differ. Options: `type: 'array'` (per-character arrays
of readings) or `type: 'all'` (per-character arrays of full detail objects); `pattern`; `toneType`;
`removeNonZh` (drop non-Chinese characters). Empty or non-string input returns `[]`.

### `addDict(dict)`

Merge additional entries into the working dictionary (used to load the complete phrase dictionary so
segmentation can group multi-character words). Each entry maps a Chinese word to its reading, and the
value may take **either** form:

- a plain pinyin string of space-joined syllables, exactly like the provided `lib/data` phrase dicts
  (e.g. `这个: 'zhè ge'`); or
- an array `[pinyin, frequency?, pos?]` whose **first element (index 0) is that same pinyin string**,
  optionally followed by a numeric word `frequency` (a probability weight the maximum-probability
  `segmentit` uses to rank candidate segmentations) at index 1 and a part-of-speech string at index 2
  (e.g. `人民日报: ['rén mín rì bào', 1.087e-09]`).

### Analysis helpers (operate on a single pinyin syllable string)

- `getInitialAndFinal(syllable)` → `{ initial, final }`. Leading `y` and `w` count as the **initial**
  (`'yan'` → `{ initial: 'y', final: 'an' }`); only a syllable that starts with a vowel is
  zero-initial, i.e. `initial: ''` (`'ou'` → `{ initial: '', final: 'ou' }`). A lone initial has
  `final: ''` (`'m'` → `{ initial: 'm', final: '' }`). This same initial/final convention also drives
  `pinyin`'s `pattern: 'initial'` / `pattern: 'final'` output.
- `getFinalParts(syllable)` → `{ head, body, tail }` — the medial (glide), main vowel, and coda of the
  final. The written medial `u` after `j`/`q`/`x` is restored to `ü` (`'juǎn'` →
  `{ head: 'ü', body: 'ǎ', tail: 'n' }`), but is left as `u` elsewhere, e.g. after `y` (`'yuè'` →
  `{ head: 'u', body: 'è', tail: '' }`). Finals with no medial have an empty `head` and the offglide
  as the tail (`'gǒu'` → `{ head: '', body: 'ǒ', tail: 'u' }`; `'liáng'` →
  `{ head: 'i', body: 'á', tail: 'ng' }`).
- `getNumOfTone(syllable)` → the tone number as a string (`'0'` for the neutral tone).

## Behaviors the library must exhibit

- **Conversion & formats:** each Chinese character maps to its pinyin from the provided dictionary;
  `toneType`, `pattern`, `type`, `v`, and `nonZh` transform the output as described above.
- **Tone sandhi (一/不), on by default:** `不` becomes 2nd tone (`bú`) before a 4th-tone syllable and
  stays `bù` otherwise; `一` becomes 2nd tone (`yí`) before a 4th-tone syllable and 4th tone (`yì`)
  before 1st/2nd/3rd-tone syllables; between a reduplicated verb both `一` and `不` take the neutral
  tone (e.g. `看一看` → `kàn yi kàn`, `想不想` → `xiǎng bu xiǎng`). With `toneSandhi:false` the base
  dictionary tones are kept (e.g. `一天` → `yī tiān`).
- **Surname mode:** with `mode:'surname'`, characters/compound surnames in the surname table take their
  surname reading (e.g. `区` → `ōu`, `曾` → `zēng`, `令狐` → `líng hú`, `万俟` → `mò qí`); `surname:'head'`
  applies this only to a leading surname. Setting `surname:'head'` (or `'all'`) on its own turns surname
  matching on even without `mode:'surname'`.
- **Multiple readings & disambiguation:** `pinyin(char, { multiple:true })` and `polyphonic(...)` return
  every reading of a character; in running text, segmentation-based disambiguation uses the phrase
  dictionaries to pick the contextually-correct reading.
- **Segmentation:** the three `segmentit` algorithms group characters into words; `segment()` returns
  those words (and their pinyin) in the requested `OutputFormat`.
- **Matching:** `match()` implements the precision / continuity / space / case rules above and reports
  character indices, correctly handling surrogate-pair (double-unicode) characters.

## setup.sh

Write a `setup.sh` in the project root. There is nothing to install or build (the harness runs the
TypeScript source directly), so it is a no-op:

```bash
#!/bin/bash
set -e
```
