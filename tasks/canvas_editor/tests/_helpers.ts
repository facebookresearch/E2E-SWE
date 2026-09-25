// Shared helpers for the canvas-editor hidden test suite. Not a *.test.ts file, so it is not
// collected as a suite; test files import from it. The editor is imported under the neutral
// anti-contamination alias `richdoc` (mapped by the harness to the agent's library entry).
import Editor from 'richdoc'

export interface Ctx {
  editor: any
  container: HTMLDivElement
  destroy: () => void
}

export function createEditor(data?: any, options?: any): Ctx {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const initial = data ?? { header: [], main: [{ value: '\n' }], footer: [] }
  const editor: any = new Editor(container, initial, options ?? {})
  const destroy = () => {
    try {
      editor.destroy?.()
    } catch {
      /* ignore */
    }
    container.remove()
  }
  return { editor, container, destroy }
}

/** getValue().data.main (zipped model). */
export function main(editor: any): any[] {
  return editor.command.getValue().data.main
}

/** First table element in the zipped main list, or undefined. */
export function firstTable(editor: any): any {
  return main(editor).find((e: any) => e.type === 'table')
}

/** First element in main matching a predicate. */
export function findEl(editor: any, pred: (e: any) => boolean): any {
  return main(editor).find(pred)
}

/** tableId of the just-inserted table (getValue strips it; getRangeContext exposes it). */
export function tableId(editor: any): string {
  const rc = editor.command.getRangeContext()
  return rc?.startElement?.id ?? rc?.endElement?.id
}

/** Type `text` into table cell (trIndex,tdIndex). */
export function fillCell(editor: any, id: string, tr: number, td: number, text: string): void {
  editor.command.executeSetPositionContext({ tableId: id, startTrIndex: tr, startTdIndex: td })
  editor.command.executeSetRange(0, 0, id, td, td, tr, tr)
  editor.command.executeInsertElementList([{ value: text }])
}

/** Position the cursor inside a single cell (for row/col/split ops). */
export function inCell(editor: any, id: string, tr: number, td: number): void {
  editor.command.executeSetPositionContext({ tableId: id, startTrIndex: tr, startTdIndex: td })
  editor.command.executeSetRange(0, 0, id, td, td, tr, tr)
}

/** Select a rectangular cell range from (tr0,td0) to (tr1,td1). */
export function selectCells(editor: any, id: string, tr0: number, td0: number, tr1: number, td1: number): void {
  editor.command.executeSetPositionContext({ tableId: id, startTrIndex: tr0, startTdIndex: td0 })
  editor.command.executeSetRange(0, 0, id, td0, td1, tr0, tr1)
}

/** Cell text grid of the first table: string[][] of concatenated cell values. */
export function cellGrid(editor: any): string[][] {
  const t = firstTable(editor)
  return t.trList.map((r: any) => r.tdList.map((d: any) => (d.value || []).map((v: any) => v.value).join('')))
}

/** Per-row td counts of the first table. */
export function rowLens(editor: any): number[] {
  return firstTable(editor).trList.map((r: any) => r.tdList.length)
}
