import { describe, it, expect } from 'vitest'
import { bumpLabel, fieldsFromRow, nextSheetLabel, sheetToPayload } from '../useSheetDrafts'

describe('useSheetDrafts', () => {
  it('fieldsFromRow：field_order 引导键序，余键按对象序续尾，nodes 不进网格', () => {
    const { fields, preserved } = fieldsFromRow({
      // MySQL JSON 乱序返回：data 键序与 field_order 不一致
      data: { c: 3, nodes: { n1: { params: {} } }, a: 1, b: 2 },
      field_desc: { a: '运单号' },
      field_order: ['b', 'a'],
    })
    expect(fields.map((f) => f.name)).toEqual(['b', 'a', 'c'])
    expect(fields.map((f) => f.valueText)).toEqual(['2', '1', '3'])
    expect(fields[1].desc).toBe('运单号')
    expect(fields[0].desc).toBe('')
    expect(preserved).toEqual({ nodes: { n1: { params: {} } } })
  })

  it('fieldsFromRow：field_order 中已不存在的键被过滤（删字段后保存不留悬空序）', () => {
    const { fields } = fieldsFromRow({ data: { a: 1 }, field_desc: null, field_order: ['a', 'gone'] })
    expect(fields.map((f) => f.name)).toEqual(['a'])
  })

  it('sheetToPayload：对象值 JSON 文本还原为对象，解析失败按字符串存', () => {
    const p = sheetToPayload('正常单', [
      { name: 'bl_no', valueText: 'BL001', desc: '运单号' },
      { name: 'extra', valueText: '{"x": 1}', desc: '' },
      { name: 'bad', valueText: '{oops', desc: '' },
    ], { nodes: { n1: {} } })
    expect(p.label).toBe('正常单')
    expect(p.data).toEqual({ nodes: { n1: {} }, bl_no: 'BL001', extra: { x: 1 }, bad: '{oops' })
    expect(p.field_desc).toEqual({ bl_no: '运单号' })  // 空描述不入
    expect(p.field_order).toEqual(['bl_no', 'extra', 'bad'])
  })

  it('nextSheetLabel：找第一个空闲 Sheet{n}', () => {
    expect(nextSheetLabel([])).toBe('Sheet1')
    expect(nextSheetLabel(['Sheet1', 'Sheet2'])).toBe('Sheet3')
    expect(nextSheetLabel(['Sheet1', 'Sheet3'])).toBe('Sheet2')
  })

  it('bumpLabel：label-副本 → label-副本2 → label-副本3', () => {
    expect(bumpLabel('正常单', [])).toBe('正常单-副本')
    expect(bumpLabel('正常单', ['正常单-副本'])).toBe('正常单-副本2')
    expect(bumpLabel('正常单', ['正常单-副本', '正常单-副本2'])).toBe('正常单-副本3')
  })
})
