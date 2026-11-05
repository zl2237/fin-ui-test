<template>
  <el-dialog
    :model-value="visible"
    width="min(600px, 92vw)"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <template #header>
      <span>页面域语义<HintTip content="任意层级都可配中文名，保存后各处页面域树按中文展示；清空即删除" /></span>
    </template>
    <div class="dialog-toolbar">
      <span class="toolbar-hint">共 {{ rows.length }} 个层级节点（{{ leafCount }} 个页面）</span>
      <span>
        <el-button link type="primary" size="small" @click="expandAll">全部展开</el-button>
        <el-button link type="primary" size="small" @click="collapseAll">全部收起</el-button>
      </span>
    </div>
    <div v-loading="loading" class="label-rows">
      <div
        v-for="row in visibleRows"
        :key="row.path"
        class="label-row"
        :class="{ 'is-group': row.depth === 0 }"
        :style="{ paddingLeft: `${row.depth * 18}px` }"
      >
        <span
          class="row-toggle"
          :class="{ 'no-child': !row.hasChildren }"
          :title="row.hasChildren ? (isCollapsed(row.path) ? '展开' : '收起') : ''"
          @click="row.hasChildren && toggle(row.path)"
        >
          <el-icon v-if="row.hasChildren" class="toggle-icon" :class="{ 'is-open': !isCollapsed(row.path) }">
            <CaretRight />
          </el-icon>
        </span>
        <span class="label-scope mono" :title="row.path">{{ row.seg }}</span>
        <span class="label-count" :title="`${row.count} 个元素`">{{ row.count }}</span>
        <el-input v-model="row.label" size="small" placeholder="中文语义，如 客商管理" clearable />
      </div>
    </div>
    <EmptyState v-if="!loading && !rows.length" description="暂无页面域，先新增或导入元素" :image-size="60" />
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CaretRight } from '@element-plus/icons-vue'
import { elementApi, scopeLabelApi, type UiElementScope } from '@/api'
import { useAppStore } from '@/stores'
import EmptyState from '@/components/EmptyState.vue'
import HintTip from './HintTip.vue'

/**
 * 页面域语义编辑弹窗（元素库 / 编排界面共用）。
 *
 * 与旧版差异：草稿行不再只有叶子域——按 page_scope 的 / 段分层展开成树（先序扁平化 + 缩进），
 * 中间层（如 financialManage、merchantManage）同样可配中文；显示端（两处左树）本就按累加路径
 * 查语义，中间层存了即生效。后端 page_scope_labels 不校验叶子，无需后端改动。
 */
const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'saved'): void }>()

const store = useAppStore()
const loading = ref(false)
const saving = ref(false)

interface LabelRow {
  path: string      // 累加路径（提交键，如 financialManage/receivable）
  seg: string       // 本段英文名（展示）
  depth: number     // 0=一级（模块）
  count: number     // 子树元素数（叶子=直属，中间层=子级求和）
  label: string     // 中文语义草稿
  hasChildren: boolean
}
const rows = ref<LabelRow[]>([])
/** 收起集合（path → true）。默认：所有父节点收起，仅一级可见 */
const collapsed = ref<Record<string, boolean>>({})
/** 打开时的语义快照：保存时只提交有变化的行（含清空→删除） */
let snapshot: Record<string, string> = {}

async function load() {
  if (!store.currentProjectId) return
  loading.value = true
  try {
    const [scopes, labels] = await Promise.all([
      elementApi.scopes(store.currentProjectId),
      scopeLabelApi.getMap(store.currentProjectId),
    ])
    snapshot = labels
    rows.value = flatten(buildTree(scopes), labels)
    collapseAll()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载页面域失败')
  } finally {
    loading.value = false
  }
}

interface TmpNode { path: string; seg: string; count: number; children: TmpNode[] }

/** 叶子域列表 → 全层级树（与元素库左树同构：按 / 切分、同段去重、中间层计数=子级和） */
function buildTree(scopes: UiElementScope[]): TmpNode[] {
  const root: TmpNode[] = []
  for (const s of scopes) {
    const segs = s.page_scope.split('/').filter(Boolean)
    let level = root
    let path = ''
    segs.forEach((seg, i) => {
      path = path ? `${path}/${seg}` : seg
      let node = level.find(n => n.seg === seg)
      if (!node) {
        node = { path, seg, count: 0, children: [] }
        level.push(node)
      }
      if (i === segs.length - 1) node.count += s.count
      level = node.children
    })
  }
  const fill = (nodes: TmpNode[]) => {
    for (const n of nodes) {
      if (n.children.length) {
        fill(n.children)
        n.count = n.children.reduce((a, c) => a + c.count, 0)
      }
    }
  }
  fill(root)
  return root
}

/** 先序扁平化（树序即展示序），挂上语义草稿 */
function flatten(nodes: TmpNode[], labels: Record<string, string>, depth = 0, out: LabelRow[] = []): LabelRow[] {
  for (const n of nodes) {
    out.push({ path: n.path, seg: n.seg, depth, count: n.count, label: labels[n.path] || '', hasChildren: n.children.length > 0 })
    flatten(n.children, labels, depth + 1, out)
  }
  return out
}

const leafCount = computed(() => rows.value.filter(r => !r.hasChildren).length)

/** 祖先任一收起即不可见 */
const visibleRows = computed(() =>
  rows.value.filter(r => !ancestorPaths(r.path).some(p => collapsed.value[p]))
)

function ancestorPaths(path: string): string[] {
  const segs = path.split('/')
  const out: string[] = []
  for (let i = 1; i < segs.length; i++) out.push(segs.slice(0, i).join('/'))
  return out
}

const isCollapsed = (path: string) => !!collapsed.value[path]
function toggle(path: string) {
  if (collapsed.value[path]) delete collapsed.value[path]
  else collapsed.value[path] = true
}
function expandAll() {
  collapsed.value = {}
}
function collapseAll() {
  const next: Record<string, boolean> = {}
  for (const r of rows.value) if (r.hasChildren) next[r.path] = true
  collapsed.value = next
}

watch(() => props.visible, (v) => { if (v) load() })

async function onSave() {
  if (!store.currentProjectId) return
  const items = rows.value
    .filter(d => (snapshot[d.path] || '') !== d.label.trim())
    .map(d => ({ page_scope: d.path, label: d.label.trim() }))
  if (!items.length) {
    emit('update:visible', false)
    return
  }
  saving.value = true
  try {
    const res = await scopeLabelApi.batch(store.currentProjectId, items)
    ElMessage.success(res.message)
    emit('update:visible', false)
    emit('saved')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.dialog-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.toolbar-hint {
  font-size: 12px;
  color: var(--app-text-faint);
}
.label-rows {
  max-height: 56vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.row-toggle {
  width: 16px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--app-text-faint);
  cursor: pointer;
}
.row-toggle.no-child {
  cursor: default;
}
.toggle-icon {
  font-size: 13px;
  transition: transform 0.15s;
}
.toggle-icon.is-open {
  transform: rotate(90deg);
}
/* 一级（模块层）加粗作分组视觉 */
.label-row.is-group .label-scope {
  font-weight: 600;
  color: var(--app-text);
}
.label-scope {
  width: 200px;
  flex-shrink: 0;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-muted);
}
.label-count {
  width: 30px;
  flex-shrink: 0;
  text-align: right;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--app-text-faint);
}
.label-row :deep(.el-input) {
  flex: 1;
}
@media (max-width: 760px) {
  .label-scope { width: 130px; }
}
.mono {
  font-family: var(--app-font-mono);
}
</style>
