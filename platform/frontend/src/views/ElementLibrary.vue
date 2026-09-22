<template>
  <div class="page">
    <div class="page-head">
      <div class="head-left">
        <span class="page-title">元素库</span>
        <el-button type="primary" @click="openCreate">+ 新增元素</el-button>
        <el-button type="success" @click="openBatch">批量导入</el-button>
        <el-button @click="customVisible = true">动作库管理</el-button>
      </div>
      <div class="head-right">
        <el-input
          v-model="keyword"
          style="width: 240px"
          placeholder="搜索元素 key / 描述"
          clearable
          @input="onSearchInput"
          @clear="onSearchInput"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
    </div>

    <div class="body">
      <!-- 左侧：页面域树（按 page_scope 的 / 层级分组，公共路由 = 模块/页面） -->
      <div class="scope-panel">
        <div class="scope-head">页面域</div>
        <el-scrollbar class="scope-scroll">
          <button
            type="button"
            class="scope-item"
            :class="{ active: !currentScope }"
            @click="selectScope('')"
          >
            <span class="scope-name">全部</span>
            <span class="scope-count">{{ totalOfScopes }}</span>
          </button>
          <el-tree
            v-if="scopeTree.length"
            :data="scopeTree"
            node-key="path"
            :props="{ label: 'label', children: 'children' }"
            :current-node-key="currentScope"
            default-expand-all
            highlight-current
            :expand-on-click-node="false"
            @node-click="onTreeNodeClick"
          >
            <template #default="{ data }">
              <span class="tree-node">
                <span class="scope-name" :title="data.path">{{ data.label }}</span>
                <span class="scope-count">{{ data.count }}</span>
              </span>
            </template>
          </el-tree>
          <EmptyState v-if="!scopes.length" description="暂无页面域，先新增或导入元素" :image-size="60" />
        </el-scrollbar>
      </div>

      <!-- 右侧：元素表格 -->
      <div class="table-wrap">
        <el-card shadow="never" class="card">
          <el-skeleton v-if="loading" :rows="5" animated class="skeleton-wrap" />
          <el-table v-else :data="pagedList" stripe size="small" row-key="id" @sort-change="onSortChange">
            <template #empty>
              <EmptyState :description="hasActiveFilter ? '没有匹配的元素，试试调整筛选条件' : '暂无元素'" :image-size="80">
                <el-button v-if="!hasActiveFilter" type="primary" @click="openCreate">新增元素</el-button>
              </EmptyState>
            </template>
            <el-table-column prop="id" label="ID" width="70" sortable="custom" />
            <el-table-column prop="element_key" label="元素 Key" min-width="180" show-overflow-tooltip sortable="custom">
              <template #default="{ row }">
                <span class="mono">{{ row.element_key }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="page_scope" label="页面域" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono">{{ row.page_scope }}</span>
              </template>
            </el-table-column>
            <el-table-column label="描述" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.description || '—' }}</template>
            </el-table-column>
            <el-table-column label="定位策略" min-width="240">
              <template #default="{ row }">
                <el-tooltip :content="strategiesText(row.strategies)" placement="top" popper-class="app-tip">
                  <span class="mono strategies-brief">{{ strategiesBrief(row.strategies) }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="更新人" width="90" align="center">
              <template #default="{ row }">{{ row.updated_by_name || '—' }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新时间" width="120" sortable="custom">
              <template #default="{ row }">
                <el-tooltip :content="formatTime(row.updated_at)" placement="top" popper-class="app-tip">
                  <span>{{ formatRelativeTime(row.updated_at) }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="onEdit(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="onRemove(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :total="list.length"
              :page-sizes="[10, 20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              small
              background
            />
          </div>
        </el-card>
      </div>
    </div>

    <!-- 新增/编辑抽屉 -->
    <el-drawer v-model="drawerVisible" :title="editing ? '编辑元素' : '新增元素'" size="min(560px, 92vw)" direction="rtl">
      <el-form :model="form" label-width="90px">
        <el-form-item label="页面域" required>
          <el-input v-model="form.page_scope" placeholder="如 ordermanage/business_order_add" />
        </el-form-item>
        <el-form-item label="元素 Key" required>
          <el-input v-model="form.element_key" placeholder="如 bl_no_input（同域唯一）" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" placeholder="如 提单号输入框" />
        </el-form-item>
        <el-form-item label="定位策略" required>
          <el-tabs v-model="stratTab" class="strat-tabs">
            <!-- 键值对编辑：key 从常用策略键选择（可输入自定义键） -->
            <el-tab-pane label="键值对" name="kv">
              <div v-for="(row, i) in kvRows" :key="i" class="kv-row">
                <el-select v-model="row.key" filterable allow-create default-first-option placeholder="策略键" class="kv-key">
                  <el-option v-for="k in STRATEGY_KEYS" :key="k" :label="k" :value="k" />
                </el-select>
                <el-input v-model="row.value" placeholder="定位值" class="kv-val" />
                <el-button link type="danger" size="small" :disabled="kvRows.length <= 1" @click="kvRows.splice(i, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="kvRows.push({ key: '', value: '' })">+ 添加策略</el-button>
              <p class="form-tip">执行时按优先级取首个命中：test_id → for → label → placeholder → button → tab → text → checkbox → toast → css → xpath → full_xpath</p>
            </el-tab-pane>
            <!-- JSON 文本域：整包编辑（高级用法/粘贴已有片段） -->
            <el-tab-pane label="JSON" name="json">
              <el-input v-model="strategiesJson" type="textarea" :rows="8" :placeholder="STRAT_PLACEHOLDER" class="mono" />
              <p v-if="jsonError" class="form-tip json-error">{{ jsonError }}</p>
            </el-tab-pane>
          </el-tabs>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-drawer>

    <!-- 自定义动作（JS 模板）管理：编排「自定义动作」步骤引用 -->
    <CustomActionDialog v-model="customVisible" />

    <!-- 批量导入弹窗：粘贴 locator JSON 原文，前端展开为 items -->
    <el-dialog v-model="batchVisible" title="批量导入元素" width="560px" align-center :close-on-click-modal="false">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <div class="batch-guide">
          <div class="guide-title">导入格式说明</div>
          <div class="guide-line">粘贴 autotest-playwright 的 locator JSON 原文：<code>{ "key": { "full_xpath": "…", "label": "…", "description": "…" } }</code></div>
          <div class="guide-line">每个顶层 key 作为一个元素，<code>description</code> 字段提为元素描述，其余字段原样作为定位策略</div>
          <div class="guide-line">覆盖式导入：同页面域同 key 更新策略，新 key 插入</div>
        </div>
      </el-alert>
      <el-form label-width="80px">
        <el-form-item label="页面域" required>
          <el-input v-model="batchScope" placeholder="本次导入的元素归属页面域，如 ordermanage/business_order_add" />
        </el-form-item>
      </el-form>
      <el-input
        v-model="batchText"
        type="textarea"
        :rows="10"
        :placeholder="BATCH_PLACEHOLDER"
      />
      <div v-if="batchPreview" style="margin-top: 8px; font-size: 12px; color: var(--app-text-muted)">
        已解析 {{ batchPreview.count }} 个元素<template v-if="batchPreview.noStrategy">，{{ batchPreview.noStrategy }} 个无定位策略字段（将跳过）</template>
      </div>
      <div v-else-if="batchError" style="margin-top: 8px; font-size: 12px; color: var(--el-color-danger)">{{ batchError }}</div>
      <template #footer>
        <el-button @click="batchVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onBatchSave">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { elementApi, type UiElement, type UiElementScope } from '@/api'
import { useAppStore } from '@/stores'
import { debounce } from '@/utils/ui'
import { formatTime, formatRelativeTime } from '@/utils/format'
import { useClientSort } from '@/composables/useClientSort'
import EmptyState from '@/components/EmptyState.vue'
import CustomActionDialog from '@/components/CustomActionDialog.vue'

const store = useAppStore()

// 自定义动作管理弹窗（页头「自定义动作」入口）
const customVisible = ref(false)

// 常用策略键（locator JSON / 后端优先级链中出现过的键；键值对编辑可自定义输入）
const STRATEGY_KEYS = [
  'test_id', 'for', 'label', 'placeholder', 'button', 'tab', 'text', 'checkbox', 'toast', 'css', 'xpath', 'full_xpath',
]

// 占位示例（内嵌单引号，模板属性内无法直排，走 script 绑定）
const STRAT_PLACEHOLDER = `{"full_xpath": "//input[@id='bl_no']", "label": "提单号"}`
const BATCH_PLACEHOLDER = `{
  "bl_no_input": {"full_xpath": "//input[@id='bl_no']", "label": "提单号", "description": "提单号输入框"},
  "submit_btn": {"text": "提交"}
}`

const scopes = ref<UiElementScope[]>([])
const list = ref<UiElement[]>([])
const loading = ref(false)
const keyword = ref('')
const currentScope = ref('')
const page = ref(1)
const pageSize = ref(10)

const totalOfScopes = computed(() => scopes.value.reduce((acc, s) => acc + s.count, 0))
const hasActiveFilter = computed(() => !!(keyword.value || currentScope.value))

// 页面域树：page_scope 按 / 分层（公共路由 模块/页面/...），父节点聚合子级元素数
interface ScopeTreeNode {
  path: string
  label: string
  count: number
  children?: ScopeTreeNode[]
}
const scopeTree = computed<ScopeTreeNode[]>(() => {
  const root: ScopeTreeNode[] = []
  for (const s of scopes.value) {
    const segs = s.page_scope.split('/').filter(Boolean)
    let level = root
    let path = ''
    segs.forEach((seg, i) => {
      path = path ? `${path}/${seg}` : seg
      let node = level.find(n => n.label === seg)
      if (!node) {
        node = { path, label: seg, count: 0 }
        level.push(node)
      }
      if (i === segs.length - 1) {
        // 叶子：元素数来自后端聚合；同路径既是叶子又有子级时合并计数
        node.count = (node.children?.length ? node.children.reduce((a, c) => a + c.count, 0) : 0) + s.count
        node.children = undefined
      } else {
        node.children = node.children || []
        level = node.children
      }
    })
  }
  // 父节点计数 = 子级之和
  const fill = (nodes: ScopeTreeNode[]) => {
    for (const n of nodes) {
      if (n.children?.length) {
        fill(n.children)
        n.count = n.children.reduce((a, c) => a + c.count, 0)
      }
    }
  }
  fill(root)
  return root
})

/** 树节点点击：叶子按精确域过滤；父节点（模块级）按路径前缀过滤 */
function onTreeNodeClick(data: ScopeTreeNode) {
  selectScope(data.path)
}

// 表头排序（sortable="custom"）：先排全量再分页切片
const { onSortChange, sorted: sortedList } = useClientSort(list, {
  id: d => d.id,
  element_key: d => d.element_key,
  updated_at: d => d.updated_at ?? '',
}, () => { page.value = 1 })

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return sortedList.value.slice(start, start + pageSize.value)
})

/** 策略 JSON 单行摘要（表格单元格）：键名列表 + 首个策略值截断 */
function strategiesBrief(s?: Record<string, any>): string {
  if (!s || !Object.keys(s).length) return '—'
  const first = Object.entries(s).find(([, v]) => v != null && v !== '')
  return first ? `${first[0]}=${String(first[1]).slice(0, 60)}` : '—'
}
function strategiesText(s?: Record<string, any>): string {
  try {
    return JSON.stringify(s ?? {}, null, 2)
  } catch {
    return String(s)
  }
}

async function loadScopes() {
  if (!store.currentProjectId) return
  try {
    scopes.value = await elementApi.scopes(store.currentProjectId)
  } catch {
    scopes.value = []
  }
}

async function load() {
  if (!store.currentProjectId) return
  loading.value = true
  try {
    // 叶子节点（后端聚合出的精确域）走服务端过滤；
    // 父节点（模块级路由前缀）拉全量后前端 startsWith 过滤
    const scope = currentScope.value
    const exact = scopes.value.some(s => s.page_scope === scope)
    let rows = await elementApi.list(store.currentProjectId, exact ? scope : undefined, keyword.value || undefined)
    if (scope && !exact) rows = rows.filter(e => e.page_scope.startsWith(scope + '/'))
    list.value = rows
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function selectScope(scope: string) {
  currentScope.value = scope
  page.value = 1
  load()
}

// 搜索输入：回第 1 页 + 300ms 防抖（避免每敲一键发一次请求）
const onSearchInput = debounce(() => {
  page.value = 1
  load()
}, 300)

// ===== 新增/编辑 =====
const drawerVisible = ref(false)
const editing = ref<UiElement | null>(null)
const saving = ref(false)
const form = ref({ page_scope: '', element_key: '', description: '' })
// 策略双编辑模式：键值对行 / JSON 文本域，切换时互相同步
const stratTab = ref<'kv' | 'json'>('kv')
const kvRows = ref<{ key: string; value: string }[]>([{ key: '', value: '' }])
const strategiesJson = ref('{}')
const jsonError = ref('')

/** 键值对行 → strategies 对象（空键/空值丢弃） */
function kvToObj(): Record<string, string> {
  const obj: Record<string, string> = {}
  for (const r of kvRows.value) {
    if (r.key.trim() && r.value.trim()) obj[r.key.trim()] = r.value
  }
  return obj
}

/** JSON 文本域解析（失败返回 null 并记录错误信息） */
function parseJson(): Record<string, any> | null {
  try {
    const obj = JSON.parse(strategiesJson.value || '{}')
    if (typeof obj !== 'object' || Array.isArray(obj) || obj === null) {
      jsonError.value = 'JSON 需为对象（{ "策略键": "定位值" }）'
      return null
    }
    jsonError.value = ''
    return obj
  } catch {
    jsonError.value = 'JSON 格式错误，请检查'
    return null
  }
}

// tab 切换同步：离开源 tab 时把内容带过去
watch(stratTab, (to, from) => {
  if (from === 'kv' && to === 'json') {
    strategiesJson.value = JSON.stringify(kvToObj(), null, 2)
  } else if (from === 'json' && to === 'kv') {
    const obj = parseJson()
    if (obj === null) {
      stratTab.value = 'json' // 解析失败留在 JSON tab 修正
      return
    }
    kvRows.value = Object.entries(obj).map(([key, value]) => ({ key, value: String(value ?? '') }))
    if (!kvRows.value.length) kvRows.value = [{ key: '', value: '' }]
  }
})

function openCreate() {
  editing.value = null
  form.value = { page_scope: currentScope.value, element_key: '', description: '' }
  kvRows.value = [{ key: '', value: '' }]
  strategiesJson.value = '{}'
  jsonError.value = ''
  stratTab.value = 'kv'
  drawerVisible.value = true
}

function onEdit(row: UiElement) {
  editing.value = row
  form.value = { page_scope: row.page_scope, element_key: row.element_key, description: row.description || '' }
  kvRows.value = Object.entries(row.strategies || {}).map(([key, value]) => ({ key, value: String(value ?? '') }))
  if (!kvRows.value.length) kvRows.value = [{ key: '', value: '' }]
  strategiesJson.value = JSON.stringify(row.strategies || {}, null, 2)
  jsonError.value = ''
  stratTab.value = 'kv'
  drawerVisible.value = true
}

/** 以当前激活 tab 的内容为准收敛 strategies */
function collectStrategies(): Record<string, any> | null {
  if (stratTab.value === 'kv') {
    const obj = kvToObj()
    if (!Object.keys(obj).length) {
      ElMessage.warning('请至少填写一条有效的定位策略（策略键 + 定位值）')
      return null
    }
    return obj
  }
  const obj = parseJson()
  if (!obj) {
    ElMessage.warning(jsonError.value)
    return null
  }
  if (!Object.keys(obj).length) {
    ElMessage.warning('策略 JSON 不能为空对象')
    return null
  }
  return obj
}

async function onSave() {
  if (!form.value.page_scope.trim() || !form.value.element_key.trim()) {
    ElMessage.warning('页面域和元素 Key 不能为空')
    return
  }
  if (!store.currentProjectId) return
  const strategies = collectStrategies()
  if (!strategies) return
  saving.value = true
  try {
    if (editing.value) {
      await elementApi.update(editing.value.id, {
        page_scope: form.value.page_scope.trim(),
        element_key: form.value.element_key.trim(),
        strategies,
        description: form.value.description.trim() || undefined,
      })
      ElMessage.success('已更新')
    } else {
      await elementApi.create({
        project_id: store.currentProjectId,
        page_scope: form.value.page_scope.trim(),
        element_key: form.value.element_key.trim(),
        strategies,
        description: form.value.description.trim() || undefined,
      })
      ElMessage.success('已新增')
    }
    drawerVisible.value = false
    await Promise.all([load(), loadScopes()])
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onRemove(row: UiElement) {
  try {
    await ElMessageBox.confirm(
      `确认删除元素「${row.page_scope}.${row.element_key}」？引用该元素的 UI 节点将执行失败，此操作不可恢复`,
      '删除元素',
      { type: 'warning', confirmButtonText: '删除' },
    )
  } catch {
    return
  }
  try {
    await elementApi.remove(row.id)
    ElMessage.success('已删除')
    await Promise.all([load(), loadScopes()])
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

// ===== 批量导入（locator JSON 覆盖式导入） =====
const batchVisible = ref(false)
const batchText = ref('')
const batchScope = ref('')
const batchError = ref('')

/** 解析 locator JSON：{key:{...,description}} → items（含无策略字段计数） */
function parseLocatorJson() {
  try {
    const obj = JSON.parse(batchText.value || '{}')
    if (typeof obj !== 'object' || Array.isArray(obj) || obj === null) {
      return { error: 'JSON 需为对象：{ "key": { 策略字段, description } }', items: [], noStrategy: 0 }
    }
    const items: { element_key: string; strategies: Record<string, any>; description?: string }[] = []
    let noStrategy = 0
    for (const [key, val] of Object.entries(obj)) {
      if (!key || typeof val !== 'object' || val === null) continue
      const { description, ...strategies } = val as Record<string, any>
      if (!Object.keys(strategies).length) {
        noStrategy++
        continue
      }
      items.push({ element_key: key, strategies, description: description || undefined })
    }
    return { error: '', items, noStrategy }
  } catch {
    return { error: 'JSON 格式错误，请粘贴合法 JSON 原文', items: [], noStrategy: 0 }
  }
}

const batchPreview = computed(() => {
  if (!batchText.value.trim()) return null
  const { items, noStrategy } = parseLocatorJson()
  if (!items.length && noStrategy === 0) return null
  return { count: items.length, noStrategy }
})

function openBatch() {
  batchText.value = ''
  batchScope.value = currentScope.value
  batchError.value = ''
  batchVisible.value = true
}

async function onBatchSave() {
  if (!batchScope.value.trim()) {
    ElMessage.warning('请填写本次导入的页面域')
    return
  }
  const { error, items } = parseLocatorJson()
  if (error) {
    batchError.value = error
    ElMessage.warning(error)
    return
  }
  if (!items.length) {
    ElMessage.warning('未解析到有效元素（key 下至少需要一个策略字段）')
    return
  }
  if (!store.currentProjectId) return
  saving.value = true
  try {
    const res = await elementApi.batch({
      project_id: store.currentProjectId,
      page_scope: batchScope.value.trim(),
      items,
    })
    ElMessage.success(res.message)
    batchVisible.value = false
    await Promise.all([load(), loadScopes()])
  } catch (e: any) {
    ElMessage.error(e.message || '导入失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadScopes()
  load()
})

// 切换项目时重新加载，确保元素按项目隔离（筛选与页码同步重置，避免携带旧项目条件）
watch(() => store.currentProjectId, (n, old) => {
  if (n !== old) {
    page.value = 1
    keyword.value = ''
    currentScope.value = ''
    loadScopes()
    load()
  }
})
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
}
/* 左侧页面域面板 */
.scope-panel {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--app-card);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  overflow: hidden;
}
.scope-head {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  border-bottom: 1px solid var(--app-border);
}
.scope-scroll {
  flex: 1;
}
.scope-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  cursor: pointer;
  border: none;
  background: transparent;
  font: inherit;
  color: inherit;
  text-align: left;
  transition: background 0.15s;
}
.scope-item:hover {
  background: var(--app-hover);
}
.scope-item:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: -2px;
}
.scope-item.active {
  background: var(--app-active);
  color: var(--app-primary);
  font-weight: 500;
}
.scope-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scope-count {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--app-text-faint);
  flex-shrink: 0;
}
/* 页面域树：节点行与平铺项同视觉，宽度撑满可点击 */
.scope-panel :deep(.el-tree) {
  --el-tree-node-content-height: 34px;
  padding: 4px 6px;
  background: transparent;
  --el-tree-expand-icon-color: var(--app-text-muted);
}
.scope-panel :deep(.el-tree-node__content) {
  border-radius: 6px;
  transition: background 0.15s;
}
.scope-panel :deep(.el-tree-node__content:hover) {
  background: var(--app-hover);
}
.scope-panel :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: var(--app-active);
  color: var(--app-primary);
  font-weight: 500;
}
.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  font-size: 13px;
}
.table-wrap {
  flex: 1;
  min-width: 0;
}
.card {
  height: 100%;
  overflow: auto;
}
.skeleton-wrap {
  padding: 20px;
}
.pagination-wrap {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.strategies-brief {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
/* 策略键值对编辑行 */
.kv-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.kv-key {
  width: 150px;
  flex-shrink: 0;
}
.kv-val {
  flex: 1;
}
.form-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
}
.json-error {
  color: var(--el-color-danger);
}
.batch-guide .guide-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.batch-guide .guide-line {
  line-height: 1.8;
  font-size: 13px;
}
.batch-guide code {
  font-family: var(--app-font-mono);
  font-size: 11px;
  background: var(--app-hover);
  padding: 1px 4px;
  border-radius: 3px;
}
</style>
