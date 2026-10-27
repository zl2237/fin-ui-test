<template>
  <el-popover
    v-if="sheets && sheets.length"
    trigger="click"
    placement="bottom-end"
    :width="340"
    :persistent="false"
    :teleported="!nested"
    popper-class="dvm-popper"
  >
    <template #reference>
      <span class="dvm-link" title="插入 ${sheet.字段} 数据集引用到光标处">+ 数据集</span>
    </template>

    <div class="dvm-body">
      <el-input v-model="keyword" size="small" clearable placeholder="搜索 sheet / 字段名" class="dvm-search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <!-- 滚动收敛在弹层内部列表（同 SqlRefMenu）；渲染截断至 LIMIT 条 -->
      <div class="dvm-list">
        <template v-for="row in visibleRows" :key="row.key">
          <div v-if="row.kind === 'title'" class="dvm-title">{{ row.label }}</div>
          <div v-else class="dvm-item" :title="`$\{${row.sheet}.${row.name}\}`"
               @click="onPick(row.sheet!, row.name!)">
            <span class="dvm-sheet">{{ row.sheet }}</span>
            <span class="dvm-dim">.</span>
            <span class="dvm-var">{{ row.name }}</span>
            <span v-if="row.desc" class="dvm-dim">（{{ row.desc }}）</span>
          </div>
        </template>
        <div v-if="!totalVars" class="dvm-empty">无匹配字段</div>
        <div v-else-if="shownVars < totalVars" class="dvm-more">
          已显示前 {{ shownVars }} 条（共 {{ totalVars }}），输入关键字缩小范围
        </div>
      </div>
      <div class="dvm-tip">选中 sheet 的字段也可裸写 ${字段}；描述列仅备注不参与执行</div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
/** ${sheet.字段} 数据集引用插入弹层（UI 动作值旁，仿 SqlRefMenu：popover +
 *  搜索 + 分组 + 渲染截断）。数据源为绑定数据集的 sheet 清单（NodeConfigDrawer
 *  懒加载并下传）——运行时只注入绑定/选中数据集的 sheet，选择器不提供其它
 *  数据集的字段。nested 语义同 SqlRefMenu（宿主在弹层内时不 teleport）。 */
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'

export interface DsVarSheet {
  label: string
  fields: { name: string; desc?: string }[]
}

const props = defineProps<{ sheets?: DsVarSheet[]; nested?: boolean }>()
const emit = defineEmits<{ (e: 'insert', text: string): void }>()

const keyword = ref('')

/** 单次渲染上限：超出部分靠搜索定位 */
const LIMIT = 120

type Row =
  | { kind: 'title'; key: string; label: string }
  | { kind: 'var'; key: string; sheet: string; name: string; desc?: string }

const allRows = computed<Row[]>(() => {
  const q = keyword.value.trim().toLowerCase()
  const rows: Row[] = []
  for (const s of props.sheets || []) {
    const fields = q
      ? s.fields.filter((f) =>
          f.name.toLowerCase().includes(q) ||
          s.label.toLowerCase().includes(q) ||
          (f.desc || '').toLowerCase().includes(q))
      : s.fields
    if (!fields.length) continue
    rows.push({ kind: 'title', key: `t:${s.label}`, label: s.label })
    for (const f of fields)
      rows.push({ kind: 'var', key: `${s.label}:${f.name}`, sheet: s.label, name: f.name, desc: f.desc })
  }
  return rows
})

const visibleRows = computed(() => allRows.value.slice(0, LIMIT))
const totalVars = computed(() => allRows.value.reduce((n, r) => (r.kind === 'var' ? n + 1 : n), 0))
const shownVars = computed(() => visibleRows.value.reduce((n, r) => (r.kind === 'var' ? n + 1 : n), 0))

function onPick(sheet: string, name: string) {
  emit('insert', `\${${sheet}.${name}}`)
  keyword.value = ''
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
.dvm-popper .dvm-tip {
  padding-top: 4px;
  border-top: 1px solid var(--app-border, #ebeef5);
  font-size: 11px;
  color: var(--app-text-faint, #c0c4cc);
}
</style>
