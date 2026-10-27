import { nextTick } from 'vue'

/**
 * SQL 输入框的 {{节点.变量}} 引用插入（消费方：SqlCell、ParamSourceForm；
 * 2026-10-27 起也承载 UI 动作值的数据集 ${sheet.字段} 插入，见 DatasetVarMenu）。
 *
 * 记录最后聚焦的输入控件，插入发生在光标处（替换选区）并回焦定位到插入串
 * 之后；从未聚焦时追加末尾。类型为 textarea | input 并集（el-input 单行渲染
 * <input>，接口同构）；setSql 由消费方提供——表格行直接改字段，表单走 patch
 * 通道，写回口径由各消费方决定。
 */
export function useSqlInsert(setSql: (next: string) => void, getSql: () => string) {
  let lastSqlTa: HTMLTextAreaElement | HTMLInputElement | null = null

  function onSqlFocus(e: FocusEvent) {
    lastSqlTa = e.target as HTMLTextAreaElement | HTMLInputElement
  }

  function onSqlInsert(t: string) {
    const ta = lastSqlTa
    const v = getSql() || ''
    if (ta) {
      const s = ta.selectionStart ?? 0
      const e = ta.selectionEnd ?? s
      setSql(v.slice(0, s) + t + v.slice(e))
      nextTick(() => {
        ta.focus()
        const pos = s + t.length
        ta.setSelectionRange(pos, pos)
      })
    } else {
      setSql(`${v}${t}`)
    }
  }

  return { onSqlFocus, onSqlInsert }
}
