# Canvas Rich-Text Document Editor

Implement a WYSIWYG rich-text **document editor** that renders onto an HTML5 `<canvas>` element.
The editor holds a structured document (a header band, a main body, and a footer band), lets the user
edit rich text and insert structured content (tables, lists, headings, hyperlinks, form controls,
separators, page breaks), and exposes a **command interface** (`editor.command`) for both programmatic
editing and reading the document back out.

You are implementing a library, in **TypeScript**, that has **no external runtime dependencies** (only
the browser DOM / Canvas API). Design the internals however you like — only the public interface and
the observable behavior described below are graded.

## Package entry & exports

The library entry point is **`src/editor/index.ts`**. It must:

- **default-export** the `Editor` class, and
- **named-export** the enums listed in the "Enums" section.

An editor instance is created with:

```ts
new Editor(container, data, options?)
```

- `container: HTMLDivElement` — the element to render into.
- `data: IEditorData | IElement[]` — the initial document. `IEditorData` is
  `{ header?: IElement[]; main: IElement[]; footer?: IElement[] }`. A bare `IElement[]` is treated as
  the `main` body. An empty document is `{ header: [], main: [{ value: '\n' }], footer: [] }`.
- `options?: IEditorOption` — configuration; all fields optional.

The instance exposes `editor.command`, the interface described under "Command API" and "Reading the
document".

## The document model (`IElement`)

The document is arrays of `IElement`. Each element is a plain object. A **text** element has a string
`value` and optional formatting fields. A **structural** element has a `type` (see `ElementType`) and
type-specific fields. Fields the public API reads or writes:

- **Text & character formatting:** `value` (string), `bold`, `italic`, `underline`, `strikeout`
  (booleans), `color`, `highlight`, `font` (strings), `size` (number).
- **Paragraph formatting:** `rowFlex` (a `RowFlex` value — alignment).
- **Paragraph break:** represented by an element whose `value` is the newline character `'\n'`.
- **List:** `listType` (a `ListType`), `listStyle` (a `ListStyle`).
- **Title (heading):** `level` (a `TitleLevel`).
- **Table:** `colgroup: { width: number }[]` and `trList: { tdList: ITd[] }[]`, where a cell `ITd` is
  `{ colspan: number; rowspan: number; value: IElement[] }` (cell content is itself an element list).
- **Hyperlink:** `url` (string) and `valueList: IElement[]` (the displayed content).
- **Separator:** `dashArray: number[]` (dash pattern; `[]` means a solid line).
- **Control (form field):** `control: { type: ControlType; conceptId: string; value: IElement[];
  placeholder?: string }`.

## Text indexing & selection

Text positions are addressed by **grapheme-cluster index** within the currently active zone (or,
when the cursor is inside a table cell, within that cell). A grapheme cluster — for example an emoji
or a base character plus combining marks — counts as **one** index position, regardless of how many
UTF-16 code units it occupies. **Index 0 of a paragraph is its leading newline.**

`executeSetRange(startIndex, endIndex, ...)` sets the selection to the **half-open range
`[startIndex, endIndex)`** — `startIndex` inclusive, `endIndex` exclusive.

## Reading the document

`getValue()`, `getText()`, and `getHTML()` are members of the `editor.command` interface, invoked as
`editor.command.getValue()`, `editor.command.getText()`, and `editor.command.getHTML()` — like the
other getters.

### `getValue(): { version, data: { header, main, footer } }`
`version` is the library version string identifying the serialization schema (informational — no
grading reads it). `data` is a **normalized** view of each band:

- Adjacent text elements that share identical formatting are **coalesced into a single element**
  (e.g. bolding the first two characters of `hello` yields a bold element for `he` and a separate
  plain element for `llo`). This coalescing is applied **recursively** to nested text content — a
  control's `value`, a table cell's content, and a hyperlink's `valueList` are each normalized the
  same way.
- A paragraph's leading newline appears as a leading `'\n'` in the `value` of that paragraph's first
  element.
- A run of consecutive list items collapses into one element
  `{ type: 'list', listType, listStyle, valueList: IElement[] }`; a run of heading text into
  `{ type: 'title', level, valueList: IElement[] }`.
- When a paragraph is converted to a **title**, that paragraph's leading newline is emitted as a
  separate leading `{ value: '\n' }` element **before** the title element — it is not folded into the
  title's `valueList` (whose text is therefore the heading text alone).
- Tables/controls/hyperlinks/separators/page breaks appear as their structural elements (with the
  fields listed above). Transient/rendering-only data is not included; an empty table cell has
  `value: []`.

Example — after inserting `hello` and bolding the first two graphemes:
`data.main` is `[{ value: '\nhe', bold: true }, { value: 'llo' }]`.

### `getText(): { header, main, footer }`
Plain-text strings for each band, with blocks concatenated in document order and each paragraph
break rendered as `'\n'`; a body's leading empty paragraph is itself such a break, so an empty body
reads back as `"\n"`. A **table**'s own serialization begins with **exactly one** leading newline,
then for each row the cells joined by **two spaces** followed by a newline — e.g. a 2×2 table of
`P,Q,R,S` serializes, on its own, to `"\nP  Q\nR  S\n"`. A table inserted into an otherwise-empty
body is preceded by that body's leading empty-paragraph `'\n'`, so the band's `getText` starts with
that `'\n'` and then the table's own single leading newline (two leading newlines before the first
row). A **list** serializes each item as `'\n'` + a marker + the item text, where the marker is
`"N."` for ordered lists (1-based, incrementing per item) and a bullet for unordered lists.

### `getHTML(): { header, main, footer }`
HTML-string serialization of each band. Character formatting is expressed as inline CSS (e.g. bold
text carries a bold `font-weight`).

## Command API (`editor.command`)

Call `executeFocus()` before programmatic editing (editing requires a live cursor/selection).

### Editing & selection
- `executeFocus()`
- `executeInsertElementList(elements: IElement[], options?)` — insert `elements` at the cursor; if
  there is a non-empty selection, it is replaced. A single call is **one atomic action** (see undo).
- `executeSelectAll()` — select all content in the active zone.
- `executeSetRange(startIndex, endIndex, tableId?, startTdIndex?, endTdIndex?, startTrIndex?, endTrIndex?)`
  — set the selection (see "Text indexing & selection"; the table arguments target a cell range).
- `executeReplaceRange(range)` — set the selection from a range object.
- `getRange()` — the current range object.
- `getRangeText(): string` — the plain text of the current selection (newline placeholders removed).
- `getRangeContext()` — descriptive information about the current selection, including the element(s)
  at the selection boundary (for a table, the boundary element is the table element, carrying its id).
- `executeSetValue(data)` — replace the entire document (this resets undo/redo history).

### Character & paragraph formatting (act on the current selection)
- `executeBold()`, `executeItalic()`, `executeUnderline()`, `executeStrikeout()` — **toggle** a
  style across the selection: if **any** selected character lacks the style, the whole selection
  gains it; only when the whole selection already has it is it cleared.
- `executeColor(value: string | null)`, `executeHighlight(value: string | null)` — set the color, or
  clear it when passed `null`.
- `executeFont(name: string)`, `executeSize(size: number)`.
- `executeRowFlex(flex: RowFlex)` — set paragraph alignment (paragraph-scoped).
- `executeFormat()` — remove **character-level** formatting from the selection, leaving
  paragraph-level attributes (such as alignment) intact.

### Lists & headings (act on the selected paragraph(s))
- `executeList(listType: ListType | null, listStyle?: ListStyle)` — apply a list; re-applying the
  same `listType`+`listStyle` **removes** it; applying the same type with a different style
  **re-styles** it; `null` removes it.
- `executeTitle(level: TitleLevel | null)` — apply a heading of the given level, or clear it with
  `null`. Applying a title stores `level` on the heading run and marks each heading **text** element
  `bold: true` with a level-dependent `size`; clearing (`null`) removes the `level`, `bold`, and
  `size` again. Empty (newline-only) lines in the selection are not converted.

### Tables
- `executeInsertTable(rows: number, cols: number)` — insert a table (each cell starts empty).
- To edit or operate on cells, first target a cell (or cell range) with
  `executeSetPositionContext({ tableId, startTrIndex, startTdIndex })` and/or `executeSetRange` using
  its table arguments. `tableId` is the table element's id (obtainable from
  `getRangeContext().startElement.id` after insertion).
- `executeMergeTableCell()` — merge the selected rectangular block into its top-left cell: that cell's
  `colspan`/`rowspan` grow to cover the block and it receives the combined content; the covered cells
  are removed. The combined content is the block's cell contents concatenated in **row-major**
  (reading) order, each source cell kept as its own paragraph separated by a `'\n'` paragraph break
  with no leading break.
- `executeCancelMergeTableCell()` — reverse a merge: the anchor cell's `colspan`/`rowspan` return to 1
  and the previously-covered cells are restored (empty).
- `executeSplitVerticalTableCell()` / `executeSplitHorizontalTableCell()` — split the current cell,
  adding a column / a row respectively. A **vertical** split divides the current cell into two
  single-column cells (the original plus a new empty cell immediately to its right); a
  **horizontal** split divides it into two single-row cells (the original plus a new empty
  single-cell row immediately below). The rest of the table adjusts so that every row still spans
  the full column count.
- `executeInsertTableTopRow()`, `executeInsertTableBottomRow()`, `executeInsertTableLeftCol()`,
  `executeInsertTableRightCol()` — insert a row/column immediately **before** (Top/Left) or **after**
  (Bottom/Right) the current cell, shifting the existing cell content aside. When a row is inserted
  adjacent to a cell that spans multiple rows (a `rowspan` cell), that cell's `rowspan` **grows** to
  cover the newly inserted row rather than a separate cell being added in the spanned column, so
  every row's cells always span the full column count.
- `executeDeleteTableRow()`, `executeDeleteTableCol()`, `executeDeleteTable()` — deleting the last
  remaining row or column removes the whole table.

### History
- `executeUndo()`, `executeRedo()` — undo/redo **one command's worth** of change (a whole
  insert/format/structural operation is a single step). Performing a new edit clears the redo stack.

### Search & replace
- `executeSearch(keyword: string | null, options?: { isRegEnable?: boolean; isIgnoreCase?: boolean })`
  — set the active search. `isIgnoreCase` defaults to `true`; `isRegEnable` treats the keyword as a
  regular expression.
- `getSearchNavigateInfo(): { index: number; count: number } | null` — the active match position
  (1-based; `0` before any navigation) and total match count; `null` when there is no keyword or no
  match.
- `getKeywordRangeList(keyword: string): IRange[]` — one range per match of `keyword`, matched using
  the active search's options as set by the most recent `executeSearch`: `isRegEnable` (treat
  `keyword` as a regular expression, so each match spans its own actual matched length) and
  `isIgnoreCase`. With no active search, `keyword` is matched literally.
- `executeSearchNavigateNext()`, `executeSearchNavigatePre()` — move the active match forward/back,
  wrapping around at the ends.
- `executeReplace(text: string, options?: { index?: number })` — replace **all** matches, or only the
  match at `index`. `index` is a **0-based** position into the ordered list of matches (`index: 0`
  targets the first match, `index: 1` the second), distinct from `getSearchNavigateInfo`'s 1-based
  display index. Replacement text **inherits the formatting of the first character of the match**.
  An empty replacement deletes the matched text.

### Zones
- `executeSetZone(zone: EditorZone)` — switch the active editing zone. Subsequent edits and
  selection getters act on that zone; `getValue`/`getText` always return all three zones. (A zone must
  be non-empty and editable to receive the cursor.)

### Structural inserts
- `executeHyperlink({ valueList: IElement[]; url: string; hyperlinkId?: string })` — insert a
  hyperlink element.
- `executeSeparator(dashArray: number[])` — insert a horizontal separator.
- `executePageBreak()` — insert a page break.

### Form controls
- `executeInsertControl(element: IElement)` — insert a control element (see `control` in the model).
- `executeSetControlValue({ conceptId: string; value: string })` — set a control's value by its
  `conceptId`.
- `getControlValue({ conceptId: string })` — return the matching control(s) as an array of objects.
  Each object's `value` is the control's current textual value as a **plain string** (the concatenated
  plain text of the control's content) — i.e. the flattened form of the model's `control.value:
  IElement[]`, not the raw element array.
- `getControlList(): IElement[]` — all control elements in the document.

## Enums (named exports; the string values are part of the contract)

- **`ElementType`**: `TEXT='text'`, `IMAGE='image'`, `TABLE='table'`, `HYPERLINK='hyperlink'`,
  `SUPERSCRIPT='superscript'`, `SUBSCRIPT='subscript'`, `SEPARATOR='separator'`,
  `PAGE_BREAK='pageBreak'`, `CONTROL='control'`, `CHECKBOX='checkbox'`, `RADIO='radio'`,
  `LATEX='latex'`, `TAB='tab'`, `DATE='date'`, `BLOCK='block'`, `TITLE='title'`, `LIST='list'`.
- **`RowFlex`**: `LEFT='left'`, `CENTER='center'`, `RIGHT='right'`, `ALIGNMENT='alignment'`,
  `JUSTIFY='justify'`.
- **`EditorZone`**: `HEADER='header'`, `MAIN='main'`, `FOOTER='footer'`.
- **`ListType`**: `UL='ul'`, `OL='ol'`.
- **`ListStyle`**: `DISC='disc'`, `CIRCLE='circle'`, `SQUARE='square'`, `DECIMAL='decimal'`,
  `CHECKBOX='checkbox'`.
- **`TitleLevel`**: `FIRST='first'`, `SECOND='second'`, `THIRD='third'`, `FOURTH='fourth'`,
  `FIFTH='fifth'`, `SIXTH='sixth'`.
- **`ControlType`**: `TEXT='text'`, `SELECT='select'`, `CHECKBOX='checkbox'`, `RADIO='radio'`,
  `DATE='date'`, `NUMBER='number'`.
