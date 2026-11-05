<template>
  <el-popover
    v-if="(sheets && sheets.length) || canAddRow"
    trigger="click"
    placement="bottom-end"
    :width="400"
    :persistent="false"
    :teleported="!nested"
    popper-class="dvm-popper"
  >
    <template #reference>
      <span class="dvm-link" title="插入 ${sheet.字段} 数据集引用到光标处；可预览值 / 临时新增一行">+ 数据集</span>
    </template>

    <div class="dvm-body">
      <!-- 新增行表单（临时定义一个值 → 存为绑定数据集新 sheet，并插入引用） -->
      <template v-if="addMode">
        <div class="dvm-add-form">
          <div class="dvm-add-title">临时新增一行（存入绑定数据集，全部 sheet 保留）</div>
          <el-input v-model="addLabel" size="small" :placeholder="`行标签（默认 ${defaultLabel}）`" class="dvm-add-input" />
          <el-input v-model="addField" size="small" placeholder="字段名（如 fee_name，不含空格/点）" class="dvm-add-input" />
          <el-input v-model="addValue" size="small" placeholder="值（支持 ${函数()} 生成表达式）" class="dvm-add-input" />
          <div class="dvm-add-ops">
            <el-button size="small" @click="addMode = false">取消</el-button>
            <el-button size="small" type="primary" :loading="addSaving" @click="onAddRow">保存并插入引用</el-button>
          </div>
        </div>
      </template>
      <!-- 常规：搜索 + 字段清单（带单元格值预览） -->
      <template v-else-if="hasSheets">
        <el-input v-model="keyword" size="small" clearable placeholder="搜索 sheet / 字段名 / 值" class="dvm-search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <!-- 滚动收敛在弹层内部列表（同 SqlRefMenu）；渲染截断至 LIMIT 条 -->
        <div class="dvm-list">
          <template v-for="row in visibleRows" :key="row.key">
            <div v-if="row.kind === 'title'" class="dvm-title">{{ row.label }}</div>
            <div v-else class="dvm-item" :title="itemTitle(row)" @click="onPick(row.sheet!, row.name!)">
              <span class="dvm-sheet">{{ row.sheet }}</span>
              <span class="dvm-dim">.</span>
              <span class="dvm-var">{{ row.name }}</span>
              <span v-if="row.value" class="dvm-val">= {{ row.value }}</span>
              <span v-else-if="row.desc" class="dvm-dim">（{{ row.desc }}）</span>
            </div>
          </template>
          <div v-if="!totalVars" class="dvm-empty">无匹配字段</div>
          <div v-else-if="shownVars < totalVars" class="dvm-more">
            已显示前 {{ shownVars }} 条（共 {{ totalVars }}），输入关键字缩小范围
          </div>
        </div>
        <div class="dvm-foot">
          <span class="dvm-tip">选中 sheet 的字段也可裸写 ${字段}；= 后为当前单元格值（生成表达式原样展示）</span>
          <a v-if="canAddRow" class="dvm-add" title="定义一个值存入绑定数据集新行，并插入引用" @click="openAdd">＋ 新增一行</a>
        </div>
      </template>
      <!-- 空态：绑定数据集暂无 sheet（新建用例已恒建 Sheet1，此处兜底清空/迁移遗留），
           新增一行不需要已有 sheet（onAddRow 整包 replaceRows，[] + 1 行满足 ≥1 校验） -->
      <div v-else class="dvm-empty-state">
        <div class="dvm-empty-text">暂无 sheet：新增一行将自动创建「{{ defaultLabel }}」并插入引用</div>
        <a class="dvm-add" @click="openAdd">＋ 新增一行</a>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
/** ${sheet.字段} 数据集引用插入弹层（UI 动作值旁，仿 SqlRefMenu：popover +
 *  搜索 + 分组 + 渲染截断）。数据源为绑定数据集的 sheet 清单（NodeConfigDrawer
 *  懒加载并下传）——运行时只注入绑定/选中数据集的 sheet，选择器不提供其它
 *  数据集的字段。nested 语义同 SqlRefMenu（宿主在弹层内时不 teleport）。
 *
 *  2026-11-04 两项能力：
 *  - 值预览：fields 携带单元格当前值（dvm-val 行内截断 + title 全文），
 *    配置节点时即可看到将执行的实际值，不必切到数据集页。
 *  - 临时新增一行：caseId + boundDatasetId 齐备时，可就地定义 字段=值 →
 *    追加为绑定数据集新 sheet（replaceRows 全量保留既有行）→ 自动插入引用。 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { caseApi, datasetApi } from '@/api'

export interface DsVarSheet {
  label: string
  fields: { name: string; desc?: string; value?: string }[]
}

const props = defineProps<{
  sheets?: DsVarSheet[]
  nested?: boolean
  /** 归属用例（新增行需要拉取绑定数据集既有行） */
  caseId?: number
  /** 用例绑定的数据集 id（新增行的落点；空=不提供新增入口） */
  boundDatasetId?: number | null
}>()
const emit = defineEmits<{
  (e: 'insert', text: string): void
  /** 新增行已落库：宿主应重载 sheet 清单（值预览同步刷新） */
  (e: 'rows-changed'): void
}>()

const keyword = ref('')

/** 单次渲染上限：超出部分靠搜索定位 */
const LIMIT = 120

type Row =
  | { kind: 'title'; key: string; label: string }
  | { kind: 'var'; key: string; sheet: string; name: string; desc?: string; value?: string }

const allRows = computed<Row[]>(() => {
  const q = keyword.value.trim().toLowerCase()
  const rows: Row[] = []
  for (const s of props.sheets || []) {
    const fields = q
      ? s.fields.filter((f) =>
          f.name.toLowerCase().includes(q) ||
          s.label.toLowerCase().includes(q) ||
          (f.desc || '').toLowerCase().includes(q) ||
          (f.value || '').toLowerCase().includes(q))
      : s.fields
    if (!fields.length) continue
    rows.push({ kind: 'title', key: `t:${s.label}`, label: s.label })
    for (const f of fields)
      rows.push({ kind: 'var', key: `${s.label}:${f.name}`, sheet: s.label, name: f.name, desc: f.desc, value: previewText(f.value) })
  }
  return rows
})

const visibleRows = computed(() => allRows.value.slice(0, LIMIT))
const totalVars = computed(() => allRows.value.reduce((n, r) => (r.kind === 'var' ? n + 1 : n), 0))
const shownVars = computed(() => visibleRows.value.reduce((n, r) => (r.kind === 'var' ? n + 1 : n), 0))

/** 行内值预览截断（title 看全文） */
function previewText(v?: string): string {
  if (!v) return ''
  return v.length > 36 ? `${v.slice(0, 36)}…` : v
}

function itemTitle(row: Extract<Row, { kind: 'var' }>): string {
  const ref = `\${${row.sheet}.${row.name}}`
  if (row.value) return `${ref} = ${row.value}`
  return row.desc ? `${ref}（${row.desc}）` : ref
}

function onPick(sheet: string, name: string) {
  emit('insert', `\${${sheet}.${name}}`)
  keyword.value = ''
}

// ===== 临时新增一行（字段=值 → 绑定数据集追加 sheet → 插入 ${label.字段}） =====
const canAddRow = computed(() => !!props.caseId && !!props.boundDatasetId)
/** 是否有 sheet：零 sheet 时弹层渲染空态（2026-11-05：新建用例已恒建 Sheet1，此处兜底） */
const hasSheets = computed(() => !!props.sheets?.length)
const addMode = ref(false)
const addSaving = ref(false)
const addLabel = ref('')
const addField = ref('')
const addValue = ref('')

/** 行标签默认提案：temp{现有 tempN 最大值+1}，避免与既有 sheet 命名空间撞名 */
const defaultLabel = computed(() => {
  let max = 0
  for (const s of props.sheets || []) {
    const m = /^temp(\d+)$/.exec(s.label)
    if (m) max = Math.max(max, Number(m[1]))
  }
  return `temp${max + 1}`
})

function openAdd() {
  addLabel.value = ''
  addField.value = ''
  addValue.value = ''
  addMode.value = true
}

async function onAddRow() {
  const field = addField.value.trim()
  if (!field) return ElMessage.warning('请填写字段名')
  if (/[.\s]/.test(field)) return ElMessage.warning('字段名不能包含空格或点（用于 ${行.字段} 引用）')
  if (!addValue.value.trim()) return ElMessage.warning('请填写值')
  if (!props.caseId || !props.boundDatasetId) return
  const label = (addLabel.value.trim() || defaultLabel.value).replace(/\s+/g, '')
  addSaving.value = true
  try {
    // 拉取绑定数据集既有行 → 原样保留 + 追加新 sheet（replaceRows 全量替换语义）
    const list = await caseApi.datasets(props.caseId)
    const bound = list.find((d) => d.id === props.boundDatasetId)
    if (!bound) throw new Error('绑定数据集不存在（可能已被删除），请在用例列表重新绑定')
    if (bound.rows.some((r) => (r.label || `Sheet${r.row_index}`) === label)) {
      ElMessage.warning(`行标签「${label}」已存在，请换一个（sheet 名即引用命名空间）`)
      return
    }
    // 零 sheet 安全：bound.rows 为空数组时 rows=[] + 新行，replaceRows 仍满足 ≥1 行校验
    const rows = bound.rows.map((r) => ({
      label: r.label || `Sheet${r.row_index}`,
      data: r.data || {},
      field_desc: r.field_desc || null,
      field_order: r.field_order || null,
    }))
    rows.push({ label, data: { [field]: addValue.value }, field_desc: { [field]: '节点配置页临时新增' }, field_order: null })
    await datasetApi.replaceRows(props.boundDatasetId, rows)
    addMode.value = false
    keyword.value = ''
    ElMessage.success(`已新增行「${label}」并插入引用；数据集其它行未改动`)
    emit('rows-changed')
    emit('insert', `\${${label}.${field}}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '新增行保存失败')
  } finally {
    addSaving.value = false
  }
}
</script>

<style scoped>
.dvm-link {
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  white-space: nowrap;
}
.dvm-link:hover {
  opacity: 0.8;
}
</style>
<style>
.dvm-popper .dvm-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dvm-popper .dvm-list {
  max-height: 300px;
  overflow-y: auto;
}
.dvm-popper .dvm-title {
  padding: 4px 4px 2px;
  font-size: 12px;
  color: var(--app-text-muted, #909399);
}
.dvm-popper .dvm-item {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 6px;
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
  min-width: 0;
}
.dvm-popper .dvm-item:hover {
  background: var(--app-hover, #f5f7fa);
}
.dvm-popper .dvm-sheet {
  flex-shrink: 0;
  color: var(--app-text-muted, #909399);
}
.dvm-popper .dvm-var {
  font-family: var(--app-font-mono, monospace);
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 40%;
}
/* 单元格值预览：= 后接值（行内截断，title 全文） */
.dvm-popper .dvm-val {
  flex: 1;
  min-width: 0;
  font-family: var(--app-font-mono, monospace);
  color: var(--app-text-muted, #909399);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dvm-popper .dvm-dim {
  color: var(--app-text-muted, #909399);
  font-size: 12px;
  flex-shrink: 0;
}
.dvm-popper .dvm-empty {
  padding: 12px 0;
  text-align: center;
  font-size: 12px;
  color: var(--app-text-faint, #c0c4cc);
}
.dvm-popper .dvm-more {
  padding: 6px 0 4px;
  text-align: center;
  font-size: 12px;
  color: var(--app-text-faint, #c0c4cc);
}
.dvm-popper .dvm-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid var(--app-border, #ebeef5);
  padding-top: 6px;
}
.dvm-popper .dvm-tip {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--app-text-faint, #c0c4cc);
}
.dvm-popper .dvm-add {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-color-primary);
  cursor: pointer;
  white-space: nowrap;
}
.dvm-popper .dvm-add:hover {
  opacity: 0.8;
}
/* 新增行表单 */
.dvm-popper .dvm-add-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dvm-popper .dvm-add-title {
  font-size: 12px;
  color: var(--app-text-muted, #909399);
  line-height: 1.5;
}
.dvm-popper .dvm-add-ops {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
/* 空态：绑定数据集零 sheet（兜底场景），引导新增首行 */
.dvm-popper .dvm-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 8px 0 4px;
}
.dvm-popper .dvm-empty-text {
  font-size: 12px;
  color: var(--app-text-muted, #909399);
  line-height: 1.5;
  text-align: center;
}
</style>
