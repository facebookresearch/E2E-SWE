import { describe, it, expect, afterEach } from 'vitest'
import {
  createEditor, firstTable, tableId, fillCell, inCell, selectCells, cellGrid, rowLens, type Ctx
} from './_helpers'

let ctx: Ctx | undefined
afterEach(() => { ctx?.destroy(); ctx = undefined })
const ed = () => (ctx = createEditor()).editor

/** Insert an r×c table and return its id. */
function table(e: any, r: number, c: number): string {
  e.command.executeFocus()
  e.command.executeInsertTable(r, c)
  return tableId(e)
}

describe('tables', () => {
  it('T1: merge a block concatenates content and sets colspan/rowspan', () => {
    const e = ed(); const id = table(e, 2, 2)
    fillCell(e, id, 0, 0, 'A'); fillCell(e, id, 0, 1, 'B'); fillCell(e, id, 1, 0, 'C'); fillCell(e, id, 1, 1, 'D')
    selectCells(e, id, 0, 0, 1, 1)
    e.command.executeMergeTableCell()
    expect(rowLens(e)).toEqual([1, 0])
    const c00 = firstTable(e).trList[0].tdList[0]
    expect({ colspan: c00.colspan, rowspan: c00.rowspan }).toEqual({ colspan: 2, rowspan: 2 })
    expect(cellGrid(e)[0][0]).toBe('A\nB\nC\nD')
  })

  it('T2: cancel-merge restores cell layout; text stays in the anchor', () => {
    const e = ed(); const id = table(e, 2, 2)
    fillCell(e, id, 0, 0, 'A'); fillCell(e, id, 0, 1, 'B'); fillCell(e, id, 1, 0, 'C'); fillCell(e, id, 1, 1, 'D')
    selectCells(e, id, 0, 0, 1, 1); e.command.executeMergeTableCell()
    inCell(e, id, 0, 0); e.command.executeCancelMergeTableCell()
    expect(rowLens(e)).toEqual([2, 2])
    const c00 = firstTable(e).trList[0].tdList[0]
    expect({ colspan: c00.colspan, rowspan: c00.rowspan }).toEqual({ colspan: 1, rowspan: 1 })
    expect(cellGrid(e)[0][0]).toBe('A\nB\nC\nD')
  })

  it('T3: split vertical adds a column and splits the cell, growing the sibling row', () => {
    const e = ed(); const id = table(e, 2, 2)
    inCell(e, id, 0, 0); e.command.executeSplitVerticalTableCell()
    expect(firstTable(e).colgroup.length).toBe(3)
    // the split row gains a cell (3 cells); the other row keeps two cells with one spanning
    expect(rowLens(e).slice().sort((a, b) => a - b)).toEqual([2, 3])
    expect(firstTable(e).trList[1].tdList[0].colspan).toBe(2)
  })

  it('T4: split horizontal adds a row and splits the cell, growing the sibling column', () => {
    const e = ed(); const id = table(e, 2, 2)
    inCell(e, id, 0, 0); e.command.executeSplitHorizontalTableCell()
    expect(firstTable(e).trList.length).toBe(3)
    // two full rows plus one split-off single-cell row; the sibling cell grows to rowspan 2
    expect(rowLens(e).slice().sort((a, b) => a - b)).toEqual([1, 2, 2])
    expect(firstTable(e).trList[0].tdList[1].rowspan).toBe(2)
  })

  it('T5: inserting a row under a rowspan cell grows the span', () => {
    const e = ed(); const id = table(e, 3, 2)
    selectCells(e, id, 0, 0, 1, 0); e.command.executeMergeTableCell() // col0 rows0-1 => rowspan 2
    inCell(e, id, 0, 0); e.command.executeInsertTableBottomRow()
    // spanning cell (row0,col0) rowspan grows to 3
    expect(firstTable(e).trList[0].tdList[0].rowspan).toBe(3)
  })

  it('T6: deleting a row that holds a rowspan cell keeps the table consistent', () => {
    const e = ed(); const id = table(e, 3, 2)
    selectCells(e, id, 0, 0, 1, 0); e.command.executeMergeTableCell()
    inCell(e, id, 0, 0); e.command.executeDeleteTableRow()
    const t = firstTable(e)
    // every row's total colspan equals the column count (2)
    for (const r of t.trList) {
      const sum = r.tdList.reduce((s: number, d: any) => s + d.colspan, 0)
      expect(sum).toBe(2)
    }
  })

  it('T7: deleting the last column removes the whole table', () => {
    const e = ed(); const id = table(e, 2, 1)
    inCell(e, id, 0, 0); e.command.executeDeleteTableCol()
    expect(firstTable(e)).toBeFalsy()
  })

  it('T8: getText serializes a table with two-space cell separators', () => {
    const e = ed(); const id = table(e, 2, 2)
    fillCell(e, id, 0, 0, 'A'); fillCell(e, id, 0, 1, 'B'); fillCell(e, id, 1, 0, 'C'); fillCell(e, id, 1, 1, 'D')
    expect(e.command.getText().main).toBe('\n\nA  B\nC  D\n')
  })

  it('T9: insert top row adds a row above', () => {
    const e = ed(); const id = table(e, 2, 2)
    inCell(e, id, 0, 0); e.command.executeInsertTableTopRow()
    expect(firstTable(e).trList.length).toBe(3)
    expect(rowLens(e)).toEqual([2, 2, 2])
  })

  it('T10: insert left column lands before the caret (existing content shifts right)', () => {
    const e = ed(); const id = table(e, 2, 2)
    fillCell(e, id, 0, 0, 'A'); fillCell(e, id, 0, 1, 'B'); fillCell(e, id, 1, 0, 'C'); fillCell(e, id, 1, 1, 'D')
    inCell(e, id, 0, 0); e.command.executeInsertTableLeftCol()
    expect(firstTable(e).colgroup.length).toBe(3)
    expect(rowLens(e)).toEqual([3, 3])
    // new (empty) column inserted at index 0; A/B and C/D shift one column to the right
    const g = cellGrid(e)
    expect([g[0][1], g[0][2]]).toEqual(['A', 'B'])
    expect([g[1][1], g[1][2]]).toEqual(['C', 'D'])
  })

  it('T11: insert right column lands after the caret (existing content keeps the edges)', () => {
    const e = ed(); const id = table(e, 2, 2)
    fillCell(e, id, 0, 0, 'A'); fillCell(e, id, 0, 1, 'B'); fillCell(e, id, 1, 0, 'C'); fillCell(e, id, 1, 1, 'D')
    inCell(e, id, 0, 0); e.command.executeInsertTableRightCol()
    expect(firstTable(e).colgroup.length).toBe(3)
    expect(rowLens(e)).toEqual([3, 3])
    // new (empty) column inserted at index 1 (right of caret col 0); A stays at col 0, B moves to col 2
    const g = cellGrid(e)
    expect([g[0][0], g[0][2]]).toEqual(['A', 'B'])
    expect([g[1][0], g[1][2]]).toEqual(['C', 'D'])
  })

  it('T12: deleting the table removes it entirely', () => {
    const e = ed(); const id = table(e, 2, 2)
    inCell(e, id, 0, 0); e.command.executeDeleteTable()
    expect(firstTable(e)).toBeFalsy()
  })
})
