<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, EditPen, Plus } from '@element-plus/icons-vue'
import { datasetApi, type DataSetSheetIn, type DataSetSheetOut } from '@/api'
import { useAppStore } from '@/stores'
import { useFieldDict } from '@/composables/useFieldDict'
import { bumpLabel, fieldsFromRow, nextSheetLabel, sheetToPayload, type SheetFieldDraft } from '@/composables/useSheetDrafts'
import EmptyState from '@/components/EmptyState.vue'

/**
 * 数据集 sheet 编辑器（2026-10-27 Excel 化，替换旧 DatasetRowsEditor）：
 * 上方网格编辑当前 sheet 的 字段名/取值/描述 三列（对象值 JSON 文本往返），
 * 底部 sheet 签切换/新增/改名/复制/删除/拖拽换序。保存 = 新形态整体替换
 * [{label, data, field_desc, field_order}]（后端重编行号 1..n）。
 *
 * - "nodes" 键（节点入参配置）不在网格渲染，随保存原样回写（preserved）
 * - field_order 引导网格键序，对抗 MySQL JSON 列不保 key 序
 * - 仅当前 sheet 的网格渲染（keyed 重建），多 sheet 大数据集不付全量渲染成本
 * - 字段名下同步显示字段字典中文名（无字典配置时零开销）
 */
const props = defineProps<{
  datasetId: number | null
  rows: DataSetSheetOut[]
}>()

const emit = defineEmits<{ (e: 'saved'): void }>()

const store = useAppStore()
const { dictLabel } = useFieldDict()
const hasDict = computed(() => Object.keys(store.fieldDictMap).length > 0)

interface SheetDraft {
  label: string
  fields: SheetFieldDraft[]
  preserved: Record<string, any>
}

const sheetDrafts = ref<SheetDraft[]>([])
const activeIdx = ref(0)
const dirty = ref(false)
const saving = ref(false)

// 上一次的 datasetId：切换数据集回到第 1 个 sheet；同数据集保存重载保持选中。
// 必须声明在下方 immediate watch 之前——immediate 回调在 setup 期即执行，
// 放后面会命中 TDZ（Cannot access before initialization）炸掉整页渲染
let lastDatasetId: number | null = null

// immediate：组件常在数据已就位后才挂载（v-if 切换），挂载即需建草稿
watch(() => [props.datasetId, props.rows], syncDrafts, { immediate: true })

function syncDrafts() {
  const dsChanged = props.datasetId !== lastDatasetId
  lastDatasetId = props.datasetId
  sheetDrafts.value = props.rows.map((r) => {
    const { fields, preserved } = fieldsFromRow(r)
    return { label: r.label || `Sheet${r.row_index}`, fields, preserved }
  })
  activeIdx.value = dsChanged ? 0 : Math.max(0, Math.min(activeIdx.value, sheetDrafts.value.length - 1))
  dirty.value = false
}

const activeSheet = computed<SheetDraft | null>(() => sheetDrafts.value[activeIdx.value] || null)

function markDirty() { dirty.value = true }

// ----- 字段校验（保存前本地拦截，后端仍兜底） -----
const dupFieldNames = computed<Set<string>>(() => {
  const s = activeSheet.value
  if (!s) return new Set()
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const f of s.fields) {
    if (!f.name) continue
    seen.has(f.name) ? dup.add(f.name) : seen.add(f.name)
  }
  return dup
})

const activeSheetInvalid = computed<string | null>(() => {
  const s = activeSheet.value
  if (!s) return null
  if (s.fields.some((f) => !f.name.trim())) return `sheet「${s.label}」有未命名字段`
  if (dupFieldNames.value.size) {
    return `sheet「${s.label}」字段名重复：${[...dupFieldNames.value].join('、')}`
  }
  return null
})

// ----- 网格操作 -----
function addField() {
  activeSheet.value?.fields.push({ name: '', valueText: '', desc: '' })
  markDirty()
}

function insertFieldBelow(i: number) {
  activeSheet.value?.fields.splice(i + 1, 0, { name: '', valueText: '', desc: '' })
  markDirty()
}

function removeField(i: number) {
  activeSheet.value?.fields.splice(i, 1)
  markDirty()
}

// ----- sheet 签操作（切换/新增/改名/复制/删除/拖拽换序） -----
function selectSheet(i: number) { activeIdx.value = i }

function addSheet() {
  const label = nextSheetLabel(sheetDrafts.value.map((s) => s.label))
  sheetDrafts.value.push({ label, fields: [], preserved: {} })
  activeIdx.value = sheetDrafts.value.length - 1
  markDirty()
}

async function renameSheet(i: number) {
  const s = sheetDrafts.value[i]
  if (!s) return
  let label: string
  try {
    const r = await ElMessageBox.prompt('sheet 新名称（用作 ${名称.字段} 引用，不可含 . $ { }）',
      '重命名 sheet', { inputValue: s.label, inputPattern: /\S+/, inputErrorMessage: '名称不能为空' })
    label = r.value.trim()
  } catch { return }
  if (label === s.label) return
  s.label = label
  markDirty()
}

function duplicateSheet(i: number) {
  const s = sheetDrafts.value[i]
  if (!s) return
  const copy: SheetDraft = {
    label: bumpLabel(s.label, sheetDrafts.value.map((x) => x.label)),
    fields: s.fields.map((f) => ({ ...f })),
    preserved: JSON.parse(JSON.stringify(s.preserved || {})),
  }
  sheetDrafts.value.splice(i + 1, 0, copy)
  activeIdx.value = i + 1
  markDirty()
}

async function removeSheet(i: number) {
  if (sheetDrafts.value.length <= 1) return
  const s = sheetDrafts.value[i]
  try {
    await ElMessageBox.confirm(
      `确认删除 sheet「${s.label}」（${s.fields.length} 个字段一并删除）？`, '删除 sheet',
      { type: 'warning' })
  } catch { return }
  sheetDrafts.value.splice(i, 1)
  if (activeIdx.value >= sheetDrafts.value.length) activeIdx.value = sheetDrafts.value.length - 1
  markDirty()
}

// 拖拽换序（同 DatasetManage 数据集条的 ds-chip 模式）
const dragIdx = ref<number | null>(null)
const overIdx = ref<number | null>(null)
const overPos = ref<'before' | 'after'>('before')

function onDragStart(i: number, e: DragEvent) {
  if (!e.dataTransfer) return
  dragIdx.value = i
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(i)) // Firefox 必需：无 payload 不启动拖拽
}

/** 悬停定位：按鼠标在目标签左/右半侧决定插前/插后 */
function onDragOver(i: number, e: DragEvent) {
  if (dragIdx.value === null || i === dragIdx.value) return
  overIdx.value = i
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  overPos.value = e.clientX < rect.left + rect.width / 2 ? 'before' : 'after'
}

function onDrop(i: number) {
  const from = dragIdx.value
  if (from === null || from === i) { resetDrag(); return }
  const item = sheetDrafts.value.splice(from, 1)[0]
  let at = i > from ? i - 1 : i
  if (overPos.value === 'after') at += 1
  sheetDrafts.value.splice(at, 0, item)
  activeIdx.value = at
  markDirty()
  resetDrag()
}

function resetDrag() {
  dragIdx.value = null
  overIdx.value = null
}

// ----- 保存（新形态整体替换） -----
function buildPayload(): DataSetSheetIn[] | null {
  const labels = new Set<string>()
  for (const s of sheetDrafts.value) {
    const label = s.label.trim()
    if (!label) { activeIdx.value = sheetDrafts.value.indexOf(s); return null }
    if (labels.has(label)) {
      activeIdx.value = sheetDrafts.value.indexOf(s)
      ElMessage.warning(`sheet 名称重复：${label}`)
      return null
    }
    labels.add(label)
    s.label = label
  }
  return sheetDrafts.value.map((s) => sheetToPayload(s.label, s.fields, s.preserved))
}

async function save() {
  if (!props.datasetId) return
  if (!sheetDrafts.value.length) { ElMessage.warning('至少保留一个 sheet'); return }
  if (activeSheetInvalid.value) { ElMessage.warning(activeSheetInvalid.value); return }
  // 非激活 sheet 的重复字段名也拦（后端不校验字段级，静默合并会丢数据）
  for (const s of sheetDrafts.value) {
    if (sheetDrafts.value.indexOf(s) === activeIdx.value) continue
    const names = s.fields.filter((f) => f.name.trim()).map((f) => f.name.trim())
    if (names.length !== new Set(names).size) {
      activeIdx.value = sheetDrafts.value.indexOf(s)
      ElMessage.warning(`sheet「${s.label}」字段名重复`)
      return
    }
    if (s.fields.some((f) => !f.name.trim())) {
      activeIdx.value = sheetDrafts.value.indexOf(s)
      ElMessage.warning(`sheet「${s.label}」有未命名字段`)
      return
    }
  }
  const payload = buildPayload()
  if (!payload) { ElMessage.warning('存在空 sheet 名称'); return }
  saving.value = true
  try {
    const ds = await datasetApi.replaceRows(props.datasetId, payload)
    ElMessage.success(`已保存 ${ds.rows.length} 个 sheet`)
    emit('saved')
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

defineExpose({ syncDrafts })
</script>

<template>
  <div class="ds-sheets-editor">
    <!-- 上方：当前 sheet 网格（字段名/取值/描述，行内编辑） -->
    <div class="ds-grid-wrap">
      <template v-if="activeSheet">
        <div class="ds-grid-head">
          <span class="ds-grid-title">{{ activeSheet.label }}</span>
          <span class="ds-grid-meta">{{ activeSheet.fields.length }} 个字段</span>
          <span v-if="activeSheet.preserved && Object.keys(activeSheet.preserved).length"
                class="ds-grid-nodes" title="节点入参配置不在网格展示，保存时原样保留">
            已保留 {{ Object.keys(activeSheet.preserved.nodes || {}).length }} 个节点入参配置
          </span>
          <span class="ds-grid-actions">
            <el-button size="small" text type="primary" @click="addField()">
              <el-icon><Plus /></el-icon>添加字段
            </el-button>
          </span>
        </div>
        <el-table :key="activeIdx" :data="activeSheet.fields" size="small" class="ds-grid"
                  empty-text="空 sheet：点「添加字段」开始录入">
          <el-table-column label="字段名" min-width="200">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" placeholder="字段名"
                        :class="{ 'is-bad': !row.name.trim() || dupFieldNames.has(row.name.trim()) }"
                        @input="markDirty" />
              <div v-if="hasDict && dictLabel(row.name)" class="ds-field-label" :title="dictLabel(row.name)">
                {{ dictLabel(row.name) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="取值" min-width="260">
            <template #default="{ row }">
              <el-input v-model="row.valueText" size="small" type="textarea"
                        :autosize="{ minRows: 1, maxRows: 8 }" placeholder="常量或 ${引用}；对象可贴 JSON"
                        @input="markDirty" />
            </template>
          </el-table-column>
          <el-table-column label="描述" min-width="160">
            <template #default="{ row }">
              <el-input v-model="row.desc" size="small" placeholder="备注（不参与执行）" @input="markDirty" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="center">
            <template #default="{ $index }">
              <el-button size="small" text title="在下方插入字段" @click="insertFieldBelow($index)">
                <el-icon><Plus /></el-icon>
              </el-button>
              <el-button size="small" text type="danger" title="删除字段" @click="removeField($index)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <EmptyState v-else description="该数据集暂无 sheet" :image-size="60" />
    </div>

    <!-- 保存条 -->
    <div class="ds-foot">
      <span class="ds-foot-left">
        <span class="ds-foot-tip">字段可写常量或 ${引用}；执行时 ${sheet名.字段} 精确取值</span>
      </span>
      <span class="ds-save-wrap">
        <span v-if="dirty" class="ds-dirty">有未保存修改</span>
        <el-button size="small" type="primary" :loading="saving" :disabled="!dirty || !datasetId"
                   @click="save">保存</el-button>
      </span>
    </div>

    <!-- 底部：sheet 签栏（切换/新增/改名/复制/删除/拖拽换序） -->
    <div class="ds-tabs">
      <div
        v-for="(s, i) in sheetDrafts"
        :key="i"
        class="ds-tab"
        :class="{
          on: i === activeIdx,
          dragging: dragIdx === i,
          'drop-before': overIdx === i && overPos === 'before',
          'drop-after': overIdx === i && overPos === 'after',
        }"
        draggable="true"
        :title="`切换到「${s.label}」；拖拽可换序`"
        @click="selectSheet(i)"
        @dblclick="renameSheet(i)"
        @dragstart="onDragStart(i, $event)"
        @dragover.prevent="onDragOver(i, $event)"
        @drop.prevent="onDrop(i)"
        @dragend="resetDrag"
      >
        <span class="ds-tab-name">{{ s.label }}</span>
        <span class="ds-tab-cnt">{{ s.fields.length }}</span>
        <span v-if="i === activeIdx" class="ds-tab-btns" @click.stop>
          <el-icon class="ds-tab-act" title="重命名（双击标签同效）" @click="renameSheet(i)"><EditPen /></el-icon>
          <el-icon class="ds-tab-act" title="复制 sheet" @click="duplicateSheet(i)"><DocumentCopy /></el-icon>
          <el-icon class="ds-tab-act ds-tab-del" title="删除 sheet"
                   :class="{ disabled: sheetDrafts.length <= 1 }" @click="removeSheet(i)"><Delete /></el-icon>
        </span>
      </div>
      <el-button size="small" class="ds-tab-add" :icon="Plus" title="新增 sheet" @click="addSheet" />
    </div>
  </div>
</template>

<style scoped>
.ds-sheets-editor {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
/* 网格区：自身滚动，sheet 签与保存条常驻 */
.ds-grid-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}
.ds-grid-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.ds-grid-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.ds-grid-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ds-grid-nodes {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 0 8px;
}
.ds-grid-actions { margin-left: auto; }
.ds-grid :deep(.el-input__inner) {
  font-family: inherit;
}
/* 字段名非法（空/重复）红显，保存前拦截 */
.ds-grid :deep(.is-bad .el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.ds-field-label {
  font-size: 11px;
  line-height: 1.3;
  color: var(--el-text-color-secondary);
  padding: 1px 8px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 保存条 */
.ds-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.ds-foot-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ds-save-wrap { display: flex; align-items: center; gap: 10px; }
.ds-dirty { font-size: 12px; color: var(--el-color-warning); }
/* 底部 sheet 签栏：Excel 呈现核心——单行横向滚动，签可拖拽换序 */
.ds-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-top: 8px;
  margin-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.ds-tab,
.ds-tab-add {
  flex-shrink: 0;
}
.ds-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px 6px 0 0;
  border-bottom: none;
  background: var(--el-fill-color-lighter);
  cursor: pointer;
  max-width: 240px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  user-select: none;
}
.ds-tab:hover { border-color: var(--el-color-primary-light-5); }
.ds-tab.on {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
}
.ds-tab.dragging { opacity: 0.35; }
.ds-tab.drop-before { box-shadow: -2px 0 0 0 var(--el-color-primary); }
.ds-tab.drop-after { box-shadow: 2px 0 0 0 var(--el-color-primary); }
.ds-tab-name {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ds-tab-cnt {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-weight: 400;
}
.ds-tab.on .ds-tab-cnt { color: var(--el-color-primary); }
.ds-tab-btns {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ds-tab-act {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  border-radius: 3px;
  padding: 1px;
}
.ds-tab-act:hover { color: var(--el-color-primary); background: var(--el-fill-color); }
.ds-tab-del:hover { color: var(--el-color-danger); }
.ds-tab-del.disabled { opacity: 0.35; cursor: not-allowed; }
</style>
