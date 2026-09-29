import { describe, it, expect, afterEach } from 'vitest'
import { createEditor, main, firstTable, type Ctx } from './_helpers'

let ctx: Ctx | undefined
afterEach(() => { ctx?.destroy(); ctx = undefined })
const ed = (data?: any, opts?: any) => (ctx = createEditor(data, opts)).editor

describe('history / undo-redo', () => {
  it('H1: multi-element insert undoes as one atomic step', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a' }, { value: 'b' }, { value: 'c' }])
    expect(e.command.getText().main).toContain('abc')
    e.command.executeUndo()
    const t = e.command.getText().main
    expect(t).not.toContain('a')
    expect(t).not.toContain('b')
    expect(t).not.toContain('c')
  })

  it('H2: a new edit invalidates the redo branch', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a' }])
    e.command.executeInsertElementList([{ value: 'b' }])
    e.command.executeUndo() // removes b
    e.command.executeInsertElementList([{ value: 'c' }])
    e.command.executeRedo() // no-op: redo branch cleared
    const t = e.command.getText().main
    expect(t).toContain('a')
    expect(t).toContain('c')
    expect(t).not.toContain('b')
  })

  it('H3: undo of a selection-replacement restores the replaced content', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hello world' }])
    e.command.executeSetRange(1, 6)
    e.command.executeInsertElementList([{ value: 'X' }]) // replaces "hello"
    expect(e.command.getText().main).toBe('\nX world')
    e.command.executeUndo()
    expect(e.command.getText().main).toBe('\nhello world')
  })

  it('H4: format on a selection is one undoable step', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hello' }])
    e.command.executeSelectAll(); e.command.executeBold()
    expect(main(e).some((el: any) => el.bold === true)).toBe(true)
    e.command.executeUndo()
    expect(main(e).some((el: any) => el.bold === true)).toBe(false)
  })

  it('H5: structural table op undoes and redoes', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertTable(2, 2)
    expect(firstTable(e)).toBeTruthy()
    e.command.executeUndo()
    expect(firstTable(e)).toBeFalsy()
    e.command.executeRedo()
    expect(firstTable(e)).toBeTruthy()
  })

  it('H6: setValue wipes the history stacks', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hello' }])
    e.command.executeSetValue({ main: [{ value: 'world' }] })
    e.command.executeUndo() // no-op
    expect(e.command.getText().main).toContain('world')
  })

  it('H7: over-undo settles at baseline without error', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a' }])
    expect(() => { e.command.executeUndo(); e.command.executeUndo(); e.command.executeUndo() }).not.toThrow()
    expect(e.command.getText().main).not.toContain('a')
  })
})
