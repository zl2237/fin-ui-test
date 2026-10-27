<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, DocumentCopy, Plus } from '@element-plus/icons-vue'
import { datasetApi } from '@/api'
import { useAppStore } from '@/stores'
import { useFieldDict } from '@/composables/useFieldDict'

/**
 * 数据集行编辑器（数据集管理页使用；用例列表只做绑定切换不再内嵌编辑）：
 * 每行一张键值卡（增删键/改名/改值，对象值折叠 JSON 编辑），
 * 复制行/删行/加行（复制上行），保存 = 整体替换后端重编行号。
 * rows 外部变更（切换数据集/重载）自动重建草稿；成功 emit('saved')。
 *
 * 大数据集（上百键 × 多行）默认折叠只展开首行，键值体 v-if 惰性渲染；
 * 键名下方同步显示字段字典中文名（无字典配置时零开销）。
 */
const props = defineProps<{
  datasetId: number | null
  rows: { row_index: number; data: Record<string, any> }[]
}>()

const emit = defineEmits<{ (e: 'saved'): void }>()

const store = useAppStore()

interface RowDraft { data: Record<string, any> }

const rowDrafts = ref<RowDraft[]>([])
const rowsDirty = ref(false)
const savingRows = ref(false)

// 折叠态：默认仅展开第 1 行；键值体不渲染，进页面只付 5 个行头的代价
const expandedRows = ref(new Set<number>())
const allExpanded = computed(() => rowDrafts.value.length > 0 && expandedRows.value.size >= rowDrafts.value.length)

function toggleRow(i: number) {
  const s = new Set(expandedRows.value)
  s.has(i) ? s.delete(i) : s.add(i)
  expandedRows.value = s
}

function expandAll() { expandedRows.value = new Set(rowDrafts.value.map((_, i) => i)) }
function collapseAll() { expandedRows.value = new Set() }

/** 折叠行头预览：前几个字段值拼一行，认得出是哪行即可 */
function rowPreview(row: RowDraft): string {
  return Object.values(row.data).slice(0, 6).map((v) => {
    const t = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '')
    return t.length > 12 ? t.slice(0, 12) + '…' : t
  }).join('  ')
}

// 字段字典中文名：直接用全局字典（MainLayout 启动/切项目时加载，字典页维护后刷新），
// 解析走 useFieldDict.dictLabel（含「节点_/sN_ 字段名」前缀剥离兼容），不再单独请求
const { dictLabel } = useFieldDict()
const hasDict = computed(() => Object.keys(store.fieldDictMap).length > 0)

// immediate：组件常在数据已就位后才挂载（v-if 切换），挂载即需建草稿
watch(() => [props.datasetId, props.rows], syncDrafts, { immediate: true, deep: false })

function syncDrafts() {
  rowDrafts.value = props.rows.map((r) => ({ data: { ...(r.data || {}) } }))
  rowsDirty.value = false
  expandedRows.value = new Set(props.rows.length ? [0] : [])
}

function markDirty() { rowsDirty.value = true }

function addRow() {
  const last = rowDrafts.value[rowDrafts.value.length - 1]
  rowDrafts.value.push({ data: last ? JSON.parse(JSON.stringify(last.data)) : {} })
  expandedRows.value = new Set([...expandedRows.value, rowDrafts.value.length - 1])
  markDirty()
}

function removeRow(i: number) {
  rowDrafts.value.splice(i, 1)
  const s = new Set<number>()
  for (const k of expandedRows.value) s.add(k > i ? k - 1 : k)
  expandedRows.value = s
  markDirty()
}

function addKey(row: RowDraft) {
  let n = 1
  while (`key${n}` in row.data) n++
  row.data[`key${n}`] = ''
  markDirty()
}

function renameKey(row: RowDraft, oldKey: string, newKey: string) {
  if (!newKey || newKey === oldKey) return
  if (newKey in row.data) { ElMessage.warning('键已存在'); return }
  const entries = Object.entries(row.data).map(([k, v]) => [k === oldKey ? newKey : k, v] as [string, any])
  row.data = Object.fromEntries(entries)
  markDirty()
}

function removeKey(row: RowDraft, key: string) {
  delete row.data[key]
  markDirty()
}

/** 值展示：对象/数组折叠成 JSON 文本编辑，保存时能解析则还原为对象 */
function valText(v: any): string {
  return typeof v === 'object' && v !== null ? JSON.stringify(v, null, 2) : String(v ?? '')
}

function setVal(row: RowDraft, key: string, text: string) {
  if (typeof row.data[key] === 'object' && row.data[key] !== null) {
    try { row.data[key] = JSON.parse(text); return } catch { /* 解析失败按字符串存 */ }
  }
  row.data[key] = text
  markDirty()
}

async function saveRows() {
  if (!props.datasetId) return
  if (!rowDrafts.value.length) { ElMessage.warning('至少保留一行数据'); return }
  savingRows.value = true
  try {
    const ds = await datasetApi.replaceRows(props.datasetId, rowDrafts.value.map((r) => r.data))
    ElMessage.success(`已保存 ${ds.rows.length} 行（行号已重编）`)
    emit('saved')
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    savingRows.value = false
  }
}

defineExpose({ syncDrafts })
</script>

<template>
  <div class="ds-rows-editor">
    <div class="ds-rows-edit">
      <div v-for="(row, i) in rowDrafts" :key="i" class="ds-row" :class="{ 'is-collapsed': !expandedRows.has(i) }">
        <div class="ds-row-head" title="点击展开/收起" @click="toggleRow(i)">
          <span class="ds-row-title">
            第 {{ i + 1 }} 行
            <span class="ds-row-count">{{ Object.keys(row.data).length }} 个字段</span>
          </span>
          <span v-if="!expandedRows.has(i) && rowPreview(row)" class="ds-row-preview">{{ rowPreview(row) }}</span>
          <span class="ds-row-btns" @click.stop>
            <el-button size="small" text title="复制本行"
                       @click="rowDrafts.splice(i + 1, 0, { data: JSON.parse(JSON.stringify(row.data)) }); expandedRows = new Set([...expandedRows, i + 1]); markDirty()">
              <el-icon><DocumentCopy /></el-icon>
            </el-button>
            <el-button size="small" text type="danger" title="删除本行" :disabled="rowDrafts.length <= 1"
                       @click="removeRow(i)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </span>
        </div>
        <div v-if="expandedRows.has(i)" class="ds-kv">
          <div v-for="key in Object.keys(row.data)" :key="key" class="ds-kv-item">
            <div class="ds-kv-keywrap">
              <el-input size="small" :model-value="key"
                        @change="(v: string) => renameKey(row, key, v.trim())" />
              <div v-if="hasDict" class="ds-kv-label" :title="dictLabel(key) || ''">{{ dictLabel(key) || '' }}</div>
            </div>
            <el-input size="small" type="textarea" autosize class="ds-kv-val"
                      :model-value="valText(row.data[key])"
                      @change="(v: string) => setVal(row, key, v)" />
            <el-button size="small" text type="danger" @click="removeKey(row, key)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button size="small" text type="primary" @click="addKey(row)">
            <el-icon><Plus /></el-icon>添加字段
          </el-button>
        </div>
      </div>
    </div>
    <div class="ds-main-foot">
      <span class="ds-foot-left">
        <el-button size="small" @click="addRow">
          <el-icon><Plus /></el-icon>添加行（复制上行）
        </el-button>
        <el-button size="small" text @click="allExpanded ? collapseAll() : expandAll()">
          {{ allExpanded ? '收起全部' : '展开全部' }}
        </el-button>
      </span>
      <span class="ds-save-wrap">
        <span v-if="rowsDirty" class="ds-dirty">有未保存修改</span>
        <el-button size="small" type="primary" :loading="savingRows" :disabled="!rowsDirty || !datasetId"
                   @click="saveRows">保存行数据</el-button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.ds-rows-editor {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.ds-rows-edit { flex: 1; overflow: auto; padding-right: 4px; }
.ds-row {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 10px;
}
.ds-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  cursor: pointer;
  user-select: none;
}
.ds-row.is-collapsed .ds-row-head { margin-bottom: 0; }
.ds-row-title { flex-shrink: 0; color: var(--el-text-color-regular); }
.ds-row-count { font-size: 12px; margin-left: 6px; }
.ds-row-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.ds-row-btns { display: flex; }
.ds-kv-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 6px;
}
.ds-kv-keywrap { width: 220px; flex-shrink: 0; }
.ds-kv-label {
  font-size: 11px;
  line-height: 1.3;
  color: var(--el-text-color-secondary);
  padding: 0 8px;
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ds-kv-val { flex: 1; }
.ds-main-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.ds-foot-left { display: flex; align-items: center; }
.ds-save-wrap { display: flex; align-items: center; gap: 10px; }
.ds-dirty { font-size: 12px; color: var(--el-color-warning); }
@media (max-width: 760px) {
  .ds-kv-keywrap { width: 130px; }
}
</style>
