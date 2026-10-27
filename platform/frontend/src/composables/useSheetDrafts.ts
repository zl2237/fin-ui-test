import type { DataSetSheetIn, DataSetSheetOut } from '@/api'

/**
 * sheet 草稿纯逻辑（DatasetSheetsEditor 的可测试内核，2026-10-27 sheet 化）：
 * - fieldsFromRow：行数据 → 网格行 [{name, valueText, desc}]，顺序 = field_order
 *   过滤现存键 + 未入序余键（MySQL JSON 列不保 key 序，显式顺序兜底）；
 *   "nodes" 键是节点入参配置，不进网格（保留原样随保存回写）
 * - sheetToPayload：草稿 → 保存载荷（preserved.nodes 合并回 data；对象值
 *   JSON 文本能解析则还原为对象，沿用旧 valText/setVal 往返口径）
 * - nextSheetLabel/bumpLabel：底部 sheet 签的缺省命名与「-副本」自增
 */

export interface SheetFieldDraft {
  name: string
  valueText: string
  desc: string
}

/** 值展示：对象/数组折叠成 JSON 文本编辑（保存时 sheetToPayload 还原） */
export function valText(v: unknown): string {
  return typeof v === 'object' && v !== null ? JSON.stringify(v, null, 2) : String(v ?? '')
}

/** 行数据 → 网格字段草稿（"nodes" 不渲染；field_order 引导键序） */
export function fieldsFromRow(row: Pick<DataSetSheetOut, 'data' | 'field_desc' | 'field_order'>): {
  fields: SheetFieldDraft[]
  preserved: Record<string, any>
} {
  const data = row.data || {}
  const desc = row.field_desc || {}
  const preserved: Record<string, any> = {}
  if ('nodes' in data) preserved.nodes = data.nodes
  const keys = Object.keys(data).filter((k) => k !== 'nodes')
  const order = (row.field_order || []).filter((k) => keys.includes(k))
  const rest = keys.filter((k) => !order.includes(k))
  const fields = [...order, ...rest].map((name) => ({
    name,
    valueText: valText(data[name]),
    desc: desc[name] || '',
  }))
  return { fields, preserved }
}

/** 草稿 → 保存载荷：对象值 JSON 文本能解析则还原；desc 空串不入 field_desc；
 *  field_order = 网格行序（含全部现存字段）；preserved.nodes 合并回 data */
export function sheetToPayload(label: string, fields: SheetFieldDraft[],
                               preserved: Record<string, any>): DataSetSheetIn {
  const data: Record<string, any> = { ...preserved }
  const fieldDesc: Record<string, string> = {}
  const fieldOrder: string[] = []
  for (const f of fields) {
    const text = f.valueText
    let value: any = text
    if (typeof text === 'string' && /^[{[]/.test(text.trim())) {
      try { value = JSON.parse(text) } catch { /* 解析失败按字符串存 */ }
    }
    if (f.name) data[f.name] = value
    if (f.name && f.desc) fieldDesc[f.name] = f.desc
    if (f.name) fieldOrder.push(f.name)
  }
  return { label, data, field_desc: fieldDesc, field_order: fieldOrder }
}

/** 下一个空闲缺省名：Sheet{1..n} 找第一个未被占用的（新增 sheet 用） */
export function nextSheetLabel(existing: string[]): string {
  const used = new Set(existing)
  let n = 1
  while (used.has(`Sheet${n}`)) n++
  return `Sheet${n}`
}

/** 复制 sheet 的默认名：label-副本 → label-副本2 → label-副本3（占用则递增） */
export function bumpLabel(label: string, existing: string[]): string {
  const used = new Set(existing)
  let base = `${label}-副本`
  if (!used.has(base)) return base
  let n = 2
  while (used.has(`${base}${n}`)) n++
  return `${base}${n}`
}
