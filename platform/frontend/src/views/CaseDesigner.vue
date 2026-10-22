<template>
  <div class="designer" v-loading="loading" element-loading-text="加载用例编排数据中...">
    <div v-if="loadError" class="app-load-error">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ loadError }}</span>
      <el-button size="small" @click="initialLoad">重试</el-button>
    </div>
    <template v-else>
    <!-- 左侧组件面板：UI 操作动作库（纯 UI 编排，接口注册面已裁撤） -->
    <div class="api-panel">
      <div class="panel-title">
        <span class="title-text">UI 操作</span>
      </div>
      <!-- 浏览器动作面板（基础+组合动作，点击添加为 UI 节点） -->
      <div class="api-list">
        <button
          v-for="a in UI_ACTIONS"
          :key="a.action"
          type="button"
          class="api-item"
          :title="`UI ${a.action}：${a.desc}`"
          @click="onAddUiNode(a.action)"
        >
          <span class="api-item-name">{{ a.name }}<span class="ui-action-key">{{ a.action }}</span></span>
          <span class="api-item-path">{{ a.desc }}</span>
        </button>
        <p class="ui-panel-tip">UI 节点由 Playwright 驱动浏览器执行，节点间在 DAG 中自由连线编排。</p>
      </div>
    </div>

    <!-- 中央画布 -->
    <div class="canvas-wrap">
      <div class="canvas-toolbar">
        <div class="toolbar-left">
          <el-button link @click="onBack">
            <el-icon><ArrowLeft /></el-icon>返回列表
          </el-button>
          <el-input v-model="caseData.name" style="width: 260px" placeholder="用例名称" />
          <el-input v-model="caseData.description" style="width: 260px" placeholder="用例描述（可选）" />
        </div>
        <div class="toolbar-right">
          <span class="dirty-tip">{{ dirty ? '有未保存改动' : '已保存' }}</span>
          <!-- 执行环境=用例绑定属性（严格绑定）：只读展示，改绑在用例列表行内。
               原全局环境选择器与执行解耦后成误导（选了 A 环境实际跑绑定环境），已移除 -->
          <EnvBadge v-if="caseData.env_id" :name="caseData.env_name" :id="caseData.env_id" />
          <el-tag v-else size="small" type="danger" effect="plain">环境未绑定</el-tag>
          <!-- dirty 圆点提示：抽屉「应用配置」只写内存，此处按钮才是持久化（双层保存语义可视化） -->
          <el-button type="primary" :class="{ 'save-dirty': dirty }" :loading="saving" @click="onSave">
            保存用例<span v-if="dirty" class="dirty-dot" aria-hidden="true" />
          </el-button>
          <el-button type="success" :loading="running" @click="onRun">执行</el-button>
        </div>
      </div>
      <!-- 画布本体层：浮动工具条的定位基准（顶栏不参与，避免 top 偏移压住执行按钮） -->
      <div class="canvas-body">
        <DagCanvas
          ref="canvasRef"
          v-model:nodes="nodes"
          v-model:edges="edges"
          :config-summary="configSummary"
          @node-open="onNodeOpen"
          @nodes-pasted="onNodesPasted"
          @link-mode-change="onLinkModeChange"
        />
        <!-- 画布浮动工具条：自动布局/连线/拆分（44e6d3b 样式与逻辑已在，此处补录遗漏的 DOM） -->
        <div class="canvas-float-bar" role="toolbar" aria-label="画布工具">
          <el-tooltip content="自动布局：整理节点与连线走向" popper-class="app-tip" placement="left" :show-after="300">
            <button type="button" class="float-btn" aria-label="自动布局" @click="onAutoLayout">
              <el-icon><Grid /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip
            :content="linkMode ? linkHint : '连线模式：依次点击源节点和目标节点'"
            popper-class="app-tip"
            placement="left"
            :show-after="300"
          >
            <button
              type="button"
              :class="['float-btn', { active: linkMode }]"
              :aria-pressed="linkMode"
              aria-label="连线模式"
              @click="onToggleLinkMode"
            >
              <el-icon><Share /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="拆分选中节点为独立用例（子流程）" popper-class="app-tip" placement="left" :show-after="300">
            <button
              type="button"
              class="float-btn"
              :disabled="!caseData.id || splitScanning"
              aria-label="拆分选中节点"
              @click="onSplit"
            >
              <el-icon v-if="splitScanning" class="spin"><Loading /></el-icon>
              <el-icon v-else><Scissor /></el-icon>
            </button>
          </el-tooltip>
        </div>
        <div class="canvas-hint">
          提示：点击左侧 UI 操作添加节点；单击选中、双击或 Enter 打开配置；Delete 删除选中节点；Ctrl+C/V 复制粘贴；Ctrl+S 保存用例；双击连线删除。
        </div>
      </div>
    </div>

    <!-- 节点配置抽屉 -->
    <NodeConfigDrawer
      v-model:visible="drawerVisible"
      :config="currentConfig"
      :ref-groups="refGroups"
      @save="onConfigSave"
    />

    <!-- 拆分确认弹窗：选中节点抽离 + 跨界变量清单 -->
    <el-dialog v-model="splitVisible" title="拆分用例" width="min(580px, 92vw)" align-center :close-on-click-modal="false">
      <div class="split-tip">
        将把选中的 {{ splitNodeIds.length }} 个节点抽离为新用例（复制其配置与内部连线），原用例保留其余节点；
        两侧之间的连线会被移除。
      </div>
      <div class="split-nodes">
        <el-tag v-for="id in splitNodeIds" :key="id" size="small" class="split-tag">{{ nodeLabel(id) }}</el-tag>
      </div>
      <template v-if="splitScan && (splitScan.outgoing.length || splitScan.incoming.length)">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="检测到跨界变量引用"
          description="以下变量在两侧用例间传递。拆分后配置原样保留，但两侧各自运行时需先执行提取方，另一侧才能取到值。"
        />
        <div class="split-vars">
          <div v-for="v in splitScan.outgoing" :key="'o-' + v.var + v.consumer" class="split-var-row">
            <el-tag size="small" type="warning">{{ nodeLabel(v.var) }}</el-tag>
            <span>该节点产出被留驻节点「{{ nodeLabel(v.consumer) }}」引用 → 拆分后原用例将取不到</span>
          </div>
          <div v-for="v in splitScan.incoming" :key="'i-' + v.var + v.consumer" class="split-var-row">
            <el-tag size="small" type="warning">{{ nodeLabel(v.var) }}</el-tag>
            <span>该节点（留驻侧）产出被抽离节点「{{ nodeLabel(v.consumer) }}」引用 → 拆分后新用例将取不到</span>
          </div>
        </div>
      </template>
      <el-alert
        v-else
        type="success"
        :closable="false"
        show-icon
        title="未检测到跨界变量引用，可安全拆分"
      />
      <el-form :model="splitForm" label-width="90px" style="margin-top: 14px">
        <el-form-item label="新用例名" required>
          <el-input v-model="splitForm.new_name" placeholder="如：付款段" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="splitVisible = false">取消</el-button>
        <el-button type="primary" :loading="splitLoading" @click="confirmSplit">确认拆分</el-button>
      </template>
    </el-dialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Grid, Share, Scissor, Loading, WarningFilled } from '@element-plus/icons-vue'
import DagCanvas from '@/components/DagCanvas.vue'
import EnvBadge from '@/components/EnvBadge.vue'
import NodeConfigDrawer from '@/components/NodeConfigDrawer.vue'
import { caseApi, type TestCase, type NodeConfig, type UiParams, type UiStep, type SplitVar } from '@/api'
import { useAppStore } from '@/stores'
import { useTabStore } from '@/stores/tabs'
import { buildRefGroups, type RefGraphCtx } from '@/composables/useRefGroups'
import type { RefVarGroup } from '@/components/VarRefSelect.vue'
import { useExecutionRunner } from '@/composables/useExecutionRunner'
import { UI_ACTIONS, uiActionName } from '@/utils/ui'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const tabStore = useTabStore()

// 执行轮询统一走 useExecutionRunner（定时器注册/卸载清理/超时策略单点管理）
const runner = useExecutionRunner()

const caseData = ref<TestCase>(emptyCase())
const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const configs = ref<NodeConfig[]>([])

/** 节点配置摘要：断言/提取计数与执行后等待（画布接线卡徽标行渲染用）。
 *  纯渲染层只读派生，不写入 node.data，因此不会进入持久化 payload */
const configSummary = computed<Record<string, { assertions: number; extracts: number; waitMs: number }>>(() => {
  const map: Record<string, { assertions: number; extracts: number; waitMs: number }> = {}
  for (const c of configs.value) {
    map[c.node_id] = {
      assertions: c.assertions?.length ?? 0,
      extracts: c.post_extract?.length ?? 0,
      waitMs: c.wait_after_ms ?? 0,
    }
  }
  return map
})
const canvasRef = ref<any>(null)
const drawerVisible = ref(false)
const selectedNodeId = ref<string | null>(null)
const saving = ref(false)
const running = ref(false)
const dirty = ref(false)
const loading = ref(false)
// 页面级加载失败（接口/用例编排数据拉取失败）：内联错误块 + 重试，不让画布静默空壳
const loadError = ref('')

async function initialLoad() {
  const id = Number(route.params.id)
  loading.value = !!id
  loadError.value = ''
  try {
    if (id) await loadCase(id)
  } catch (e: any) {
    loadError.value = e?.message || '加载用例编排数据失败'
  } finally {
    loading.value = false
  }
}
const linkMode = ref(false)
const linkSourceSelected = ref(false)

function emptyCase(): TestCase {
  return {
    id: 0,
    project_id: store.currentProjectId || 0,
    name: '',
    description: '',
    dag_config: { nodes: [], edges: [] },
    node_configs: [],
  }
}

const linkHint = computed(() => {
  if (!linkSourceSelected.value) return '连线模式：点击源节点'
  return '连线模式：点击目标节点'
})

const currentConfig = computed<NodeConfig>(() => {
  if (!selectedNodeId.value) {
    return { node_id: '', api_id: null, post_extract: [], assertions: [], wait_after_ms: 0 }
  }
  const found = configs.value.find((c) => c.node_id === selectedNodeId.value)
  if (found) return found
  // UI 节点兜底：画布节点 data 已携带 step_type/ui_action，配置缺失时按其初始化（统一动作组形态）
  const nodeData = nodes.value.find((n) => n.id === selectedNodeId.value)?.data || {}
  const fresh: NodeConfig = {
    node_id: selectedNodeId.value,
    api_id: null,
    ...(nodeData.step_type === 'ui' ? {
      step_type: 'ui',
      ui_params: {
        steps: [{ action: (nodeData.ui_action && nodeData.ui_action !== 'steps' ? nodeData.ui_action : 'goto') as UiStep['action'] }],
      },
    } : {}),
    pre_process: [],
    post_extract: [],
    assertions: [],
    wait_after_ms: 0,
  }
  configs.value.push(fresh)
  return fresh
})

async function loadCase(id: number) {
  const c = await caseApi.get(id)
  caseData.value = c
  nodes.value = (c.dag_config?.nodes || []).map((n: any) => ({ ...n }))
  edges.value = (c.dag_config?.edges || []).map((e: any) => ({ ...e }))
  configs.value = (c.node_configs || []).map((nc: NodeConfig) => ({ ...nc }))
  // deep watch(nodes/edges) 是异步批处理：同步置 false 会被随后触发的回调翻回 true，
  // 导致「打开即脏」误弹未保存提示。须等 watch 回调跑完（nextTick 后）再复位（与 EnvEdit 同法）
  await nextTick()
  dirty.value = false
}

function onBack() {
  router.push('/cases')
}

// ===== 拆分（选中节点抽离成新用例：先扫描跨界变量 → 弹窗确认 → 执行）=====
const splitVisible = ref(false)
const splitScanning = ref(false)
const splitLoading = ref(false)
const splitNodeIds = ref<string[]>([])
const splitScan = ref<{ outgoing: SplitVar[]; incoming: SplitVar[] } | null>(null)
const splitForm = ref<{ new_name: string; new_group_id: number | null }>({ new_name: '', new_group_id: null })

// 节点 id → 显示名（画布节点存了接口名）
function nodeLabel(id: string): string {
  const n = nodes.value.find((x) => x.id === id)
  return n?.data?.label || n?.label || id
}

// ===== 引用选择器数据源：产出 = 本节点/上游节点的提取名（数据集面已裁撤，UI 步骤值走 ${} 表达式） =====
/** 节点静态产出变量（与后端 validation._productions 对齐）：节点配置的提取名 */
function nodeProductions(nid: string): string[] {
  const out = new Set<string>()
  const cfg = configs.value.find((c) => c.node_id === nid)
  for (const r of cfg?.post_extract || []) {
    if (r?.name) out.add(r.name)
  }
  return [...out]
}

/** 反向 BFS 与上游/本节点分组构建已收敛至 composables/useRefGroups */
const refGraphCtx: RefGraphCtx = {
  orderedIds: () => nodes.value.map((n) => n.id),
  labelOf: nodeLabel,
  edges: () => edges.value,
  productionsOf: nodeProductions,
  selfBodyOf: () => undefined,
  selfLabel: '本节点参数值（请求后可引用）',
  // 本节点提取变量：提取按配置顺序逐行注册，后面的行可 {{本节点.提取名}} 引用前面的行
  extraGroups: (nid) => {
    const selfExtracts = ((configs.value.find((c) => c.node_id === nid)?.post_extract || [])
      .map((r: any) => r?.name).filter(Boolean)) as string[]
    if (!selfExtracts.length) return []
    return [{
      key: 'self-extract',
      label: '本节点提取变量（前面的行可引用）',
      items: [{ node_id: nid, node_label: `${nodeLabel(nid)}（本节点）`, vars: selfExtracts.map((p) => ({ path: p })) }],
    }]
  },
}

/** 当前选中节点的引用分组（供 VarRefSelect / 断言与提取的 SQL 引用） */
const refGroups = computed<RefVarGroup[]>(() => {
  const nid = selectedNodeId.value
  if (!nid) return []
  return buildRefGroups(nid, refGraphCtx)
})

async function onSplit() {
  if (!caseData.value.id) return ElMessage.warning('请先保存用例后再拆分')
  if (dirty.value) return ElMessage.warning('画布有未保存改动，请先保存再拆分')
  const selected = canvasRef.value?.getSelectedNodes?.() || []
  if (!selected.length) return ElMessage.warning('请先在画布选中要抽离的节点（框选或 Shift 多选）')
  if (selected.length >= nodes.value.length) return ElMessage.warning('至少要保留一个节点在原用例')

  splitNodeIds.value = selected.map((n: any) => n.id)
  splitScanning.value = true
  try {
    splitScan.value = await caseApi.scanSplit(caseData.value.id, splitNodeIds.value)
    // 新用例默认沿用原用例分组，列表里可再移动
    splitForm.value = { new_name: `${caseData.value.name}-拆分`, new_group_id: caseData.value.group_id ?? null }
    splitVisible.value = true
  } catch (e: any) {
    ElMessage.error(e.message || '拆分扫描失败')
  } finally {
    splitScanning.value = false
  }
}

async function confirmSplit() {
  if (!splitForm.value.new_name?.trim()) return ElMessage.warning('请输入新用例名称')
  splitLoading.value = true
  try {
    const res = await caseApi.split(caseData.value.id, {
      node_ids: splitNodeIds.value,
      new_name: splitForm.value.new_name.trim(),
      new_group_id: splitForm.value.new_group_id,
    })
    ElMessage.success(res.message)
    splitVisible.value = false
    // 原用例已收缩：重载画布（loadCase 会复位 dirty）
    await loadCase(caseData.value.id)
    ElMessageBox.confirm(
      `新用例「${res.new_case.name}」（${res.new_case.dag_config?.nodes?.length || 0} 节点）已生成，是否前往编排？`,
      '拆分完成',
      { type: 'success', confirmButtonText: '前往新用例', cancelButtonText: '留在本页' },
    ).then(() => {
      router.push(`/cases/designer/${res.new_case.id}`)
    }).catch(() => {})
  } catch (e: any) {
    ElMessage.error(e.message || '拆分失败')
  } finally {
    splitLoading.value = false
  }
}

// ===== 未保存改动防丢失（浏览器标签模型）：切换标签不弹窗不关签（多开并行编辑），
// dirty 上报全局登记；关闭标签（X/右键/批量）时由 MainLayout 统一弹未保存确认。
// 刷新/关闭浏览器仍由 beforeunload 原生拦截。
watch(dirty, (v) => tabStore.setDirty(route.path, v ? '用例编排' : null), { immediate: true })

const onBeforeUnload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onUnmounted(() => window.removeEventListener('beforeunload', onBeforeUnload))

/** 添加 UI 操作节点：不绑 api_id，页面级动作组（steps），首步为拖选的动作 */
function onAddUiNode(action: string) {
  const id = `node_${Date.now()}`
  const position = canvasRef.value?.findFreePosition?.() ?? { x: 80, y: 60 }
  const name = uiActionName(action)
  const node = {
    id,
    position,
    data: { label: name, step_type: 'ui', ui_action: 'steps', ui_steps_len: 1 },
    label: name,
  }
  nodes.value.push(node)
  canvasRef.value?.addNode(node)
  configs.value.push({
    node_id: id,
    api_id: null,
    step_type: 'ui',
    ui_params: { steps: [{ action: action as UiStep['action'] }] },
    pre_process: [],
    post_extract: [],
    assertions: [],
    wait_after_ms: 0,
  })
  dirty.value = true
}

/** 双击/回车打开节点配置抽屉 */
function onNodeOpen(id: string) {
  if (linkMode.value) return
  selectedNodeId.value = id
  drawerVisible.value = true
}

/** 粘贴节点：克隆对应 config（深拷贝 post_extract/assertions 避免共享引用） */
function onNodesPasted(mapping: { oldId: string; newId: string }[]) {
  for (const { oldId, newId } of mapping) {
    const src = configs.value.find((c) => c.node_id === oldId)
    if (src) {
      configs.value.push(JSON.parse(JSON.stringify({
        ...src,
        node_id: newId,
      })))
    }
  }
  dirty.value = true
}

function onConfigSave(_config: NodeConfig) {
  const idx = configs.value.findIndex((c) => c.node_id === _config.node_id)
  if (idx >= 0) configs.value[idx] = { ..._config }
  const nd = nodes.value.find((n) => n.id === _config.node_id)
  if (nd && _config.step_type === 'ui' && _config.ui_params?.steps?.length) {
    // UI 组节点：同步画布徽标（UI·组N动作）与首步名，保持画布可读
    nd.data.ui_action = 'steps'
    nd.data.ui_steps_len = _config.ui_params.steps.length
  }
  dirty.value = true
}

function onAutoLayout() {
  canvasRef.value?.autoLayout()
  dirty.value = true
}

function onToggleLinkMode() {
  const newMode = canvasRef.value?.toggleLinkMode()
  linkMode.value = newMode
  linkSourceSelected.value = false
  if (newMode) {
    ElMessage.info('连线模式已开启：依次点击源节点和目标节点')
    // 监听源节点选择状态
    watch(
      () => canvasRef.value?.linkSourceId,
      (v) => { linkSourceSelected.value = !!v },
      { immediate: true }
    )
  } else {
    ElMessage.info('连线模式已关闭')
  }
}

// DagCanvas 内部 Esc 退出 linkMode 时同步本组件状态
function onLinkModeChange(active: boolean) {
  linkMode.value = active
  if (!active) {
    linkSourceSelected.value = false
  }
}

// 画布变更同步
watch(nodes, () => { dirty.value = true }, { deep: true })
watch(edges, () => { dirty.value = true }, { deep: true })

async function onSave(): Promise<boolean> {
  if (!caseData.value.id) {
    ElMessage.warning('请从用例管理进入编排')
    return false
  }
  saving.value = true
  try {
    // 保存前 trim 后置提取的字符串字段，防止前后空格导致后续注入失败
    const cleanedConfigs = configs.value.map((c: NodeConfig) => ({
      ...c,
      post_extract: (c.post_extract || []).map((r: any) => ({
        ...r,
        name: typeof r.name === 'string' ? r.name.trim() : r.name,
        json_path: typeof r.json_path === 'string' ? r.json_path.trim() : r.json_path,
        sql: typeof r.sql === 'string' ? r.sql.trim() : r.sql,
        field: typeof r.field === 'string' ? r.field.trim() : r.field,
      })),
    }))
    const payloadNodes = nodes.value.map((n: any) => ({
      id: n.id,
      position: n.position,
      data: n.data,
      label: n.label,
    }))
    await caseApi.update(caseData.value.id, {
      name: caseData.value.name,
      description: caseData.value.description || '',
      dag_config: { nodes: payloadNodes, edges: edges.value },
      node_configs: cleanedConfigs,
    })
    // 同步回本地，保持 UI 与已保存数据一致
    configs.value = cleanedConfigs
    dirty.value = false
    ElMessage.success('已保存')
    return true
  } catch (e: any) {
    ElMessage.error(e.message)
    return false
  } finally {
    saving.value = false
  }
}

async function onRun() {
  if (!caseData.value.id) return ElMessage.warning('请先保存用例')
  // 整用例执行走用例绑定环境；保存失败即中断：避免「跑的是旧数据」
  const saved = await onSave()
  if (!saved) return
  running.value = true
  try {
    // 执行→进度消息→轮询→三态 favicon→结果提示；finally 复位 running（含成功/失败/超时）
    const cur = await runner.runWithFeedback(caseData.value.id)
    router.push(`/reports/${cur.id}`)
  } catch (e: any) {
    ElMessage.error(e.message || '轮询执行状态失败')
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  await initialLoad()
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  // 执行轮询定时器由 useExecutionRunner 统一清理
})

function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    onSave()
  }
}
</script>

<style scoped>
.designer {
  display: flex;
  gap: 12px;
  height: calc(100vh - 100px);
}
/* 加载失败块：根容器是横向 flex，独占一行撑满宽（否则被压成窄条） */
.designer > .app-load-error {
  width: 100%;
  align-self: center;
  margin: 0 20px;
}
.api-panel {
  width: 280px;
  background: var(--app-card);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  font-weight: 600;
  font-size: 13px;
  border-bottom: 1px solid var(--app-border);
}
.title-text {
  flex: 1;
}
.panel-search {
  margin: 8px 10px 0;
}
.api-list {
  flex: 1;
  overflow: auto;
  padding: 8px;
}
.group-block {
  margin-bottom: 4px;
}
.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 32px;
  padding: 0 10px;
  cursor: pointer;
  user-select: none;
  border-radius: var(--app-radius-sm);
  transition: background 0.15s;
  /* 语义化 button：清除浏览器默认外观 */
  appearance: none;
  font: inherit;
  color: inherit;
  text-align: left;
  background: transparent;
  border: none;
}
.group-header:hover {
  background: var(--app-hover);
}
.group-header:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: -2px;
}
.expand-icon {
  font-size: 14px;
  color: var(--app-text-muted);
  flex-shrink: 0;
  transition: transform 0.18s ease;
}
.expand-icon.expanded {
  transform: rotate(90deg);
}
.expand-spacer {
  width: 14px;
  flex-shrink: 0;
}
.group-name {
  font-size: 13px;
  color: var(--app-text);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-count {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--app-text-faint);
  flex-shrink: 0;
}
.api-item {
  display: block;
  width: 100%;
  padding: 8px 14px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  border-left: 2px solid transparent;
  /* 语义化 button：清除浏览器默认外观 */
  appearance: none;
  font: inherit;
  color: inherit;
  text-align: left;
  background: transparent;
  border-top: none;
  border-right: none;
  border-bottom: none;
}
.api-item:hover {
  background: var(--app-chip-bg);
  border-left-color: var(--app-primary);
}
.api-item:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: -2px;
}
.api-item-name {
  font-size: 13px;
  font-weight: 500;
}
.api-item-path {
  font-size: 11px;
  color: var(--app-text-muted);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* UI 动作英文 key 徽标（中文名右侧 mono 小字） */
.ui-action-key {
  margin-left: 6px;
  font-family: var(--app-font-mono);
  font-size: 10px;
  color: var(--app-text-faint);
}
.ui-panel-tip {
  margin: 10px 6px;
  font-size: 11px;
  color: var(--app-text-faint);
  line-height: 1.6;
}
.canvas-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
/* 画布本体层：顶栏之外的部分（画布 + 浮动工具条 + 快捷键提示）。
   relative 交给本层——浮动工具条 top 偏移从画布顶部起算，
   不再覆盖到顶栏右侧的执行/保存按钮 */
.canvas-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative; /* 浮动工具条定位基准 */
}
/* 画布浮动工具条：贴画布右上角（自动布局/连线/拆分），顶栏因此只留主流程四件 */
.canvas-float-bar {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 6; /* 画布内容之上；低于节点配置抽屉/弹窗 */
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--app-card-solid);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-sm);
}
.float-btn {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--app-text-muted);
  border-radius: var(--app-radius-sm);
  cursor: pointer;
  font-size: 14px;
}
.float-btn:hover {
  background: color-mix(in srgb, var(--app-primary) 12%, transparent);
  color: var(--app-primary);
}
/* 连线模式激活：琥珀语义（沿用原 warning 按钮含义），文字色加深保对比度 */
.float-btn.active {
  background: color-mix(in srgb, var(--app-warn-accent) 20%, transparent);
  color: color-mix(in srgb, var(--app-warn-text) 80%, black);
}
.float-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.float-btn:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: -2px;
}
.float-btn .spin {
  animation: float-spin 1s linear infinite;
}
@keyframes float-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .float-btn .spin { animation: none; }
}
.canvas-toolbar {
  display: flex;
  flex-wrap: wrap; /* 平板窄视口：左右两组换行而非溢出裁剪 */
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  background: var(--app-card);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  padding: 10px 14px;
}
.toolbar-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
/* 允许收缩（覆盖模板内联 260px 的刚性），窄屏降至 min-width */
.toolbar-left :deep(.el-input) {
  flex: 0 1 260px;
  min-width: 140px;
}
.toolbar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.toolbar-right :deep(.el-select) {
  flex: 0 1 160px;
  min-width: 128px;
}
.dirty-tip {
  white-space: nowrap;
}
.dirty-tip {
  font-size: 12px;
  color: var(--app-text-muted);
}
.canvas-hint {
  font-size: 12px;
  color: var(--app-text-muted);
  padding: 0 4px;
  /* 快捷键提示降噪折衷：0.85（纯辅助信息，hover 全亮；0.55 版本有效对比过低） */
  opacity: 0.85;
  transition: opacity 0.15s ease;
}
.canvas-hint:hover {
  opacity: 1;
}
/* 保存按钮未保存标记：呼吸圆点 + 轻微描边强调，保存完成即消失 */
.dirty-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #fff;
  margin-left: 6px;
  animation: dirty-pulse 1.2s ease-in-out infinite;
}
.save-dirty {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--el-color-warning) 45%, transparent);
}
@keyframes dirty-pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .dirty-dot { animation: none; opacity: 1; }
}
:deep(.canvas-wrap .dag-canvas) {
  flex: 1;
  border: 1px solid var(--app-border);
}
/* ===== 拆分确认弹窗 ===== */
.split-tip {
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
  margin-bottom: 10px;
}
.split-nodes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.split-vars {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
}
.split-var-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.split-var-row .el-tag {
  flex-shrink: 0;
}
</style>
