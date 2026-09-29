import { describe, it, expect, afterEach } from 'vitest'
import { ListType, ListStyle, TitleLevel } from 'richdoc'
import { createEditor, main, type Ctx } from './_helpers'

let ctx: Ctx | undefined
afterEach(() => { ctx?.destroy(); ctx = undefined })
const ed = (data?: any, opts?: any) => (ctx = createEditor(data, opts)).editor

describe('lists / titles', () => {
  it('L1: ordered list renumbers sequentially across items', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([
      { value: 'a' }, { value: '\n' }, { value: 'b' }, { value: '\n' }, { value: 'c' }
    ])
    e.command.executeSelectAll()
    e.command.executeList(ListType.OL, ListStyle.DECIMAL)
    // a, b, c serialize as consecutive ordered items whose "N." markers increment by one, each item
    // being '\n' + marker + text (the documented list shape); the starting number is left free.
    const txt = e.command.getText().main
    const items = [...txt.matchAll(/\n(\d+)\.([abc])/g)]
    expect(items.map((m: any) => m[2])).toEqual(['a', 'b', 'c'])
    const nums = items.map((m: any) => Number(m[1]))
    expect(nums).toEqual([nums[0], nums[0] + 1, nums[0] + 2])
  })

  it('L2: re-issuing the same list type+style toggles it off cleanly', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a' }])
    e.command.executeSelectAll(); e.command.executeList(ListType.UL, ListStyle.DISC)
    expect(main(e).some((el: any) => el.type === 'list')).toBe(true)
    e.command.executeSelectAll(); e.command.executeList(ListType.UL, ListStyle.DISC)
    const m = main(e)
    expect(m.some((el: any) => el.type === 'list')).toBe(false)
    expect(m.some((el: any) => el.listType || el.listStyle)).toBe(false)
  })

  it('L3: applying a different style re-styles rather than toggling off', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a' }])
    e.command.executeSelectAll(); e.command.executeList(ListType.UL, ListStyle.DISC)
    e.command.executeSelectAll(); e.command.executeList(ListType.UL, ListStyle.SQUARE)
    const listEl = main(e).find((el: any) => el.type === 'list')
    expect(listEl).toBeTruthy()
    expect(listEl.listStyle).toBe(ListStyle.SQUARE)
  })

  it('L5: title applies size+bold to text and skips the empty leading line', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'Heading' }])
    e.command.executeSelectAll()
    e.command.executeTitle(TitleLevel.FIRST)
    const m = main(e)
    const title = m.find((el: any) => el.type === 'title')
    expect(title.level).toBe('first')
    expect(title.valueList.map((v: any) => v.value).join('')).toBe('Heading')
    expect(title.valueList.every((v: any) => v.bold === true)).toBe(true)
    // the leading empty paragraph is not converted to a title
    expect(m[0]).toEqual({ value: '\n' })
  })

  it('L6: clearing a title removes the derived size/bold/level', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'Heading' }])
    e.command.executeSelectAll(); e.command.executeTitle(TitleLevel.SECOND)
    e.command.executeSelectAll(); e.command.executeTitle(null)
    const m = main(e)
    expect(m.some((el: any) => el.type === 'title')).toBe(false)
    expect(m.some((el: any) => el.level || el.size || el.bold)).toBe(false)
  })
})
