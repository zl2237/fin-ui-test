<template>
  <div class="page">
    <div class="page-head">
      <div class="head-left">
        <span class="page-title">数据集</span>
      </div>
      <div class="head-right">
        <span class="head-tip">每个数据集是一套完整变体行；执行面板可选行，缺省取第 1 行。多场景 = 复制后改值</span>
      </div>
    </div>

    <!-- 左用例分组树 + 右该用例数据集（用例维度，数据集互相隔离） -->
    <div v-loading="loading" class="group-layout">
      <aside class="group-side">
        <template v-for="row in sideRows" :key="row.kind === 'group' ? `g${row.id}` : `c${row.id}`">
          <!-- 分组节点：折叠/展开组内用例 -->
          <div
            v-if="row.kind === 'group'"
            class="side-node"
            :style="{ paddingLeft: 10 + row.depth * 14 + 'px' }"
            @click="toggleGroup(row.id)"
          >
            <el-icon v-if="groupHasContent(row.id)" class="expand-icon" :class="{ expanded: isExpanded(row.id) }"><CaretRight /></el-icon>
            <span v-else class="expand-spacer" />
            <el-tooltip :content="row.name" placement="top" popper-class="app-tip" :disabled="row.name.length <= 12">
              <span class="side-name">{{ row.name }}</span>
            </el-tooltip>
            <span class="side-cnt">{{ groupDatasetCount(row.id) }}</span>
          </div>
          <!-- 用例节点：选中查看其数据集 -->
          <div
            v-else
            class="side-node"
            :class="{ on: currentCase?.id === row.id }"
            :style="{ paddingLeft: 10 + row.depth * 14 + 'px' }"
            @click="selectCaseById(row.id)"
          >
            <span class="expand-spacer" />
            <el-icon class="case-icon"><Document /></el-icon>
            <el-tooltip :content="row.name" placement="top" popper-class="app-tip" :disabled="row.name.length <= 12">
              <span class="side-name">{{ row.name }}</span>
            </el-tooltip>
            <span class="side-cnt">{{ caseDatasetCount(row.id) }}</span>
          </div>
        </template>
        <EmptyState v-if="!loading && !cases.length" description="当前项目暂无用例" :image-size="60" />
      </aside>

      <div class="group-main">
        <div v-if="loadError" class="app-load-error">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ loadError }}</span>
          <el-button size="small" @click="load">重试</el-button>
        </div>

        <EmptyState v-else-if="!loading && !currentCase" description="选择左侧用例查看其数据集" />

        <template v-else-if="currentCase">
          <!-- 该用例的数据集切换条（chip 可拖拽排序，顺序按用户记忆） -->
          <div class="ds-bar">
            <div
              v-for="d in orderedCaseDatasets"
              :key="d.id"
              class="ds-chip"
              :class="{
                on: current?.id === d.id,
                dragging: dragId === d.id,
                'drop-before': overId === d.id && overPos === 'before',
                'drop-after': overId === d.id && overPos === 'after',
              }"
              draggable="true"
              @click="select(d)"
              @dragstart="onDragStart(d, $event)"
              @dragover.prevent="onDragOver(d, $event)"
              @drop.prevent="onDrop(d)"
              @dragend="resetDrag"
            >
              <span class="ds-name">{{ d.name }}</span>
              <span v-if="currentCase.dataset_id === d.id" class="ds-bound">使用中</span>
              <span class="ds-cnt">{{ d.rows.length }} 行</span>
            </div>
            <el-button size="small" class="ds-add" :icon="Plus" @click="createDataset()">新建数据集</el-button>
          </div>

          <EmptyState
            v-if="!caseDatasets.length"
            description="该用例暂无数据集。点「新建数据集」建立一套变体行"
          />

          <template v-else-if="current">
            <div class="main-head">
              <span class="main-title">{{ current.name }}</span>
              <span class="row-count">{{ current.rows.length }} 行 · 绑定用例 {{ current.case_bound_count || 0 }}</span>
              <div class="main-actions">
                <el-button v-if="current.id !== currentCase.dataset_id" size="small" type="success" plain
                           @click="bindDataset(current)">设为绑定</el-button>
                <el-button v-else size="small" plain @click="bindDataset(null)">解绑</el-button>
                <el-button size="small" @click="copyDataset">复制</el-button>
                <el-button size="small" @click="renameDataset">改名</el-button>
                <el-button size="small" type="danger" link @click="removeDataset">删除</el-button>
              </div>
            </div>

            <DatasetRowsEditor
              :dataset-id="current.id"
              :rows="current.rows"
              class="ds-editor"
              @saved="onRowsSaved"
            />
          </template>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CaretRight, Document, Plus, WarningFilled } from '@element-plus/icons-vue'
import { caseApi, caseGroupApi, datasetApi, type CaseGroup, type DataSetManage, type TestCase } from '@/api'
import { useGroupTree, type GroupTreeNode } from '@/composables/useGroupTree'
import { useAppStore } from '@/stores'
import EmptyState from '@/components/EmptyState.vue'
import DatasetRowsEditor from '@/components/DatasetRowsEditor.vue'

/**
 * 数据集管理页（数据集编辑的唯一入口，参考 API 测试平台同名页）：左用例分组树（带数据集计数）
 * → 右该用例数据集切换条（使用中标记）→ 行编辑（DatasetRowsEditor）。
 * 用例列表只做绑定切换，编辑都在本页；上次访问记忆（按项目）。
 */
const store = useAppStore()
const cases = ref<TestCase[]>([])
const groups = ref<CaseGroup[]>([])
const datasets = ref<DataSetManage[]>([])
const currentCase = ref<TestCase | null>(null)
const currentId = ref<number | null>(null)
const loading = ref(false)
const loadError = ref('')

const caseDatasets = computed(() => datasets.value.filter((d) => d.case_id === currentCase.value?.id))
const current = computed(() => caseDatasets.value.find((d) => d.id === currentId.value)
  || caseDatasets.value[0] || null)

// ----- 数据集条拖拽排序（用户级记忆：按 用户|项目|用例 存展示顺序，与 LAST_KEY 同走 localStorage） -----
const ORDER_KEY = 'fin_ui_ds_order'
const savedDsOrder = ref<number[]>([]) // 原始记忆 id 序列（含已删除也无妨，匹配不上自然沉底）
const dragId = ref<number | null>(null)
const overId = ref<number | null>(null)
const overPos = ref<'before' | 'after'>('before')

function dsOrderStorageKey(): string {
  return `${store.user?.username ?? ''}|${store.currentProjectId}|${currentCase.value?.id ?? ''}`
}

function readDsOrder() {
  savedDsOrder.value = []
  try {
    const raw = JSON.parse(localStorage.getItem(ORDER_KEY) || '{}')
    const ids = raw?.[dsOrderStorageKey()]
    if (Array.isArray(ids)) savedDsOrder.value = ids.filter((id) => typeof id === 'number')
  } catch { /* 损坏数据忽略，按默认序展示 */ }
}

function writeDsOrder() {
  try {
    const raw = JSON.parse(localStorage.getItem(ORDER_KEY) || '{}')
    raw[dsOrderStorageKey()] = savedDsOrder.value
    localStorage.setItem(ORDER_KEY, JSON.stringify(raw))
  } catch { /* 存储失败忽略 */ }
}

/** 展示顺序 = 记忆序在前，未记忆（新建）的按后端返回序稳定续尾 */
const orderedCaseDatasets = computed(() => {
  const rank = new Map(savedDsOrder.value.map((id, i) => [id, i]))
  return [...caseDatasets.value].sort((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity))
})

watch(() => currentCase.value?.id, readDsOrder, { immediate: true })

function onDragStart(d: DataSetManage, e: DragEvent) {
  if (!e.dataTransfer) return
  dragId.value = d.id
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(d.id)) // Firefox 必需：无 payload 不启动拖拽
}

/** 悬停定位：按鼠标在目标 chip 左/右半侧决定插前/插后 */
function onDragOver(d: DataSetManage, e: DragEvent) {
  if (dragId.value === null || d.id === dragId.value) return
  overId.value = d.id
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  overPos.value = e.clientX < rect.left + rect.width / 2 ? 'before' : 'after'
}

function onDrop(d: DataSetManage) {
  const from = dragId.value
  if (from === null || from === d.id) { resetDrag(); return }
  const ids = orderedCaseDatasets.value.map((x) => x.id).filter((id) => id !== from)
  const at = ids.indexOf(d.id)
  ids.splice(overPos.value === 'before' ? at : at + 1, 0, from)
  savedDsOrder.value = ids
  writeDsOrder()
  resetDrag()
}

function resetDrag() {
  dragId.value = null
  overId.value = null
}

// ===== 左侧用例分组树 =====
const UNGROUPED_ID = -1
const {
  tree: groupTree,
  isExpanded,
  toggleExpand: toggleGroup,
  expandedIds,
} = useGroupTree(groups, computed(() => store.currentProjectId), 'datasetManage')

function casesOfGroup(gid: number | null) {
  return cases.value.filter((c) => (c.group_id ?? null) === gid)
}

/** 分组可展开：有子分组或组内直接有用例 */
function groupHasContent(id: number) {
  if (id === UNGROUPED_ID) return casesOfGroup(null).length > 0
  return groups.value.some((g) => g.parent_id === id) || casesOfGroup(id).length > 0
}

/** 分组节点计数：组内直接用例 + 全部子孙分组用例的数据集合计 */
function groupDatasetCount(id: number) {
  const sum = (gid: number | null) =>
    casesOfGroup(gid).reduce((n, c) => n + caseDatasetCount(c.id), 0)
  if (id === UNGROUPED_ID) return sum(null)
  const ids: number[] = [id]
  for (let i = 0; i < ids.length; i++) {
    for (const g of groups.value) {
      if (g.parent_id === ids[i] && !ids.includes(g.id)) ids.push(g.id)
    }
  }
  return ids.reduce((n, gid) => n + sum(gid), 0)
}

function caseDatasetCount(caseId: number) {
  return datasets.value.filter((d) => d.case_id === caseId).length
}

interface SideRow { kind: 'group' | 'case'; id: number; name: string; depth: number }

const sideRows = computed<SideRow[]>(() => {
  const out: SideRow[] = []
  const walk = (nodes: GroupTreeNode[], depth: number) => {
    for (const n of nodes) {
      out.push({ kind: 'group', id: n.id, name: n.label, depth })
      if (isExpanded(n.id)) {
        casesOfGroup(n.id).forEach((c) => out.push({ kind: 'case', id: c.id, name: c.name, depth: depth + 1 }))
        walk(n.children, depth + 1)
      }
    }
  }
  walk(groupTree.value, 0)
  out.push({ kind: 'group', id: UNGROUPED_ID, name: '未分组', depth: 0 })
  if (isExpanded(UNGROUPED_ID)) {
    casesOfGroup(null).forEach((c) => out.push({ kind: 'case', id: c.id, name: c.name, depth: 1 }))
  }
  return out
})

// ----- 上次访问记忆（按项目）：进入页面直接回到上次的用例与数据集 -----
const LAST_KEY = 'fin_ui_ds_last'
function readLast(): { caseId?: number; datasetId?: number } {
  try {
    const raw = JSON.parse(localStorage.getItem(LAST_KEY) || '{}')
    return raw?.projectId === store.currentProjectId ? raw : {}
  } catch { return {} }
}
function writeLast() {
  try {
    localStorage.setItem(LAST_KEY, JSON.stringify({
      projectId: store.currentProjectId,
      caseId: currentCase.value?.id,
      datasetId: current.value?.id,
    }))
  } catch { /* 存储失败忽略 */ }
}

// ===== 加载 =====
async function load(keepCase = true) {
  if (!store.currentProjectId) return
  loading.value = true
  loadError.value = ''
  try {
    const [cs, gs, ds] = await Promise.all([
      caseApi.list(store.currentProjectId),
      caseGroupApi.list(store.currentProjectId).catch(() => [] as CaseGroup[]),
      datasetApi.list({ project_id: store.currentProjectId }),
    ])
    // 套件不持有数据集（成员各自绑定），左侧树不展示
    cases.value = cs.filter((c) => c.case_type !== 'suite')
    groups.value = gs
    datasets.value = ds
    // 首次（无展开记忆）默认全展开（含未分组虚拟节点）
    if (localStorage.getItem(`fin_group_expand_datasetManage_${store.currentProjectId}`) === null) {
      expandedIds.value = [...gs.map((g) => g.id), UNGROUPED_ID]
    }
    if (keepCase && currentCase.value) {
      currentCase.value = cases.value.find((c) => c.id === currentCase.value!.id) || null
    }
    if (!currentCase.value && cases.value.length) {
      const last = readLast()
      currentCase.value = cases.value.find((c) => c.id === last.caseId) || cases.value[0]
    }
    if (currentCase.value && !caseDatasets.value.some((d) => d.id === currentId.value)) {
      const last = readLast()
      currentId.value = caseDatasets.value.find((d) => d.id === last.datasetId && d.case_id === currentCase.value!.id)?.id
        || caseDatasets.value[0]?.id || null
    }
    writeLast()
  } catch (e: any) {
    loadError.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function selectCaseById(id: number) {
  const c = cases.value.find((x) => x.id === id)
  if (!c) return
  currentCase.value = c
  const last = readLast()
  currentId.value = caseDatasets.value.find((d) => d.id === last.datasetId && d.case_id === c.id)?.id
    || caseDatasets.value[0]?.id || null
  writeLast()
}

function select(d: DataSetManage) {
  currentId.value = d.id
  writeLast()
}

// ===== 数据集级操作（本页是数据集编辑的唯一入口；用例列表只做绑定切换） =====
async function createDataset() {
  if (!currentCase.value) return
  let name: string
  try {
    const r = await ElMessageBox.prompt('新数据集名称', '新建数据集', {
      inputValue: `场景${caseDatasets.value.length + 1}`,
      inputPattern: /\S+/, inputErrorMessage: '名称不能为空',
    })
    name = r.value.trim()
  } catch { return }
  try {
    const ds = await datasetApi.create({ case_id: currentCase.value.id, name })
    ElMessage.success(`已创建「${ds.name}」`)
    currentId.value = ds.id
    await load()
    writeLast()
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  }
}

async function renameDataset() {
  if (!current.value) return
  try {
    const r = await ElMessageBox.prompt('数据集新名称', '改名', {
      inputValue: current.value.name, inputPattern: /\S+/, inputErrorMessage: '名称不能为空',
    })
    await datasetApi.update(current.value.id, { name: r.value.trim() })
    await load()
  } catch (e: any) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}

async function copyDataset() {
  if (!current.value) return
  try {
    const ds = await datasetApi.copy(current.value.id)
    ElMessage.success(`已复制为「${ds.name}」`)
    currentId.value = ds.id
    await load()
    writeLast()
  } catch (e: any) {
    ElMessage.error(e.message || '复制失败')
  }
}

async function removeDataset() {
  if (!current.value) return
  try {
    await ElMessageBox.confirm(
      `确认删除数据集「${current.value.name}」（${current.value.rows.length} 行数据一并删除）？`, '删除数据集',
      { type: 'warning' })
  } catch { return }
  try {
    await datasetApi.remove(current.value.id)
    ElMessage.success('已删除')
    currentId.value = null
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败（被绑定时先解绑）')
  }
}

async function bindDataset(ds: DataSetManage | null) {
  if (!currentCase.value) return
  try {
    await caseApi.update(currentCase.value.id, { dataset_id: ds?.id ?? null })
    ElMessage.success(ds ? `已绑定「${ds.name}」（执行缺省取第 1 行）` : '已解绑')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '绑定失败')
  }
}

/** 行编辑保存完成：重载（行数徽标/计数） */
async function onRowsSaved() {
  await load()
}

onMounted(load)
watch(() => store.currentProjectId, () => {
  currentCase.value = null
  currentId.value = null
  load(false)
})
</script>

<style scoped>
.head-tip {
  font-size: 12px;
  color: var(--app-text-muted);
}
.case-icon {
  font-size: 14px;
  color: var(--app-text-faint);
}
.side-node.on .case-icon {
  color: var(--app-primary);
}
/* 数据集切换条：单行横向滚动 */
.ds-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  overflow-x: auto;
  margin-bottom: 12px;
}
.ds-bar .ds-chip,
.ds-bar .ds-add {
  flex-shrink: 0;
}
.ds-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-card);
  cursor: pointer;
  max-width: 280px;
  font-size: 13px;
  color: var(--app-text-muted);
}
.ds-chip:hover {
  border-color: var(--app-primary);
}
/* 拖拽排序反馈：被拖项半透明，插入位置以 2px 竖线指示 */
.ds-chip.dragging {
  opacity: 0.35;
}
.ds-chip.drop-before {
  box-shadow: -2px 0 0 0 var(--app-primary);
}
.ds-chip.drop-after {
  box-shadow: 2px 0 0 0 var(--app-primary);
}
.ds-chip.on {
  border-color: var(--app-primary);
  color: var(--app-primary);
  background: var(--app-active);
}
.ds-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ds-bound {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 8px;
  background: var(--app-active);
  color: var(--app-primary);
}
.ds-chip.on .ds-bound {
  background: var(--app-primary);
  color: #fff;
}
.ds-cnt {
  font-size: 11px;
  color: var(--app-text-faint);
}
.ds-chip.on .ds-cnt {
  color: var(--app-primary);
}
.ds-add {
  border-style: dashed;
}
.main-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.main-title {
  font-size: 15px;
  font-weight: 600;
}
.row-count {
  font-size: 12px;
  color: var(--app-text-faint);
}
.main-actions {
  margin-left: auto;
  display: flex;
  gap: 4px;
}
/* 高度链闭环：.page 定高（全站列表页同款）→ group-layout/group-main 限高，
   行编辑区在自身内部滚动（DatasetRowsEditor 自带 flex:1 + overflow），
   顶部数据集切换条与 main-head 常驻不随行滚动滚走 */
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--app-bg);
}
</style>
