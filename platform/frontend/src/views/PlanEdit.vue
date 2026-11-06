<template>
  <div class="page">
    <!-- 顶栏：返回 + 方案名编辑 + 保存/执行 -->
    <div class="page-head">
      <div class="head-left">
        <el-button @click="router.push('/plans')">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
        <span class="page-title">方案编辑</span>
        <el-input v-if="plan" v-model="name" style="width: 260px" placeholder="方案名称" maxlength="200" @input="dirty = true" />
        <el-tag v-if="plan" type="primary" effect="plain">方案 #{{ planId }}</el-tag>
      </div>
      <div class="head-right">
        <el-button :disabled="!dirty" :loading="saving" @click="onSave()">保存 (Ctrl+S)</el-button>
        <el-button type="success" :loading="running" @click="onExecute">一键执行</el-button>
      </div>
    </div>

    <div v-loading="loading" class="edit-body">
      <div v-if="loadError" class="app-load-error">
        <el-icon><WarningFilled /></el-icon>
        <span>{{ loadError }}</span>
        <el-button size="small" @click="load">重试</el-button>
      </div>

      <template v-else-if="plan">
        <el-card shadow="never" class="member-card">
          <template #header>
            <div class="card-head">
              <div class="head-title">
                <span>方案成员</span>
                <span class="member-count">{{ items.length }} 个</span>
              </div>
              <el-button type="primary" size="small" :icon="Plus" @click="addVisible = true">添加成员</el-button>
            </div>
          </template>

          <!-- 执行设置：模式 + 模式相关参数 + 描述（模式语义常显一行，不再藏 ? 提示） -->
          <div class="settings-strip">
            <el-radio-group v-model="mode" size="small" @change="dirty = true">
              <el-radio-button value="combo">并行组合</el-radio-button>
              <el-radio-button value="chain">串行链</el-radio-button>
            </el-radio-group>
            <template v-if="mode === 'chain'">
              <span class="strip-label">默认轮数</span>
              <el-input-number v-model="rounds" :min="1" :max="9999" size="small" controls-position="right" style="width: 100px" @change="dirty = true" />
              <span class="strip-label">轮间并发</span>
              <el-input-number v-model="concurrency" :min="1" :max="16" size="small" controls-position="right" style="width: 92px" @change="dirty = true" />
            </template>
            <template v-else>
              <span class="strip-label">并发上限</span>
              <el-input-number v-model="concurrency" :min="1" :max="16" size="small" controls-position="right" style="width: 92px" @change="dirty = true" />
            </template>
            <el-input v-model="description" class="strip-desc" placeholder="方案描述（可选）" maxlength="500" @input="dirty = true" />
          </div>
          <div class="mode-hint">
            <template v-if="mode === 'chain'">
              轮内按序串行 · 成功输出可传下一棒（下一棒以 __prev__.变量名 引用） · 上游失败阻断本轮下游 · 第 r 轮各成员取数据集第 r 行（不足沿用末行）
            </template>
            <template v-else>
              成员相互独立并行执行 · 失败互不影响 · 并发为提交上限（成员含 UI 用例时上限 2 = 同时存活的浏览器槽位）
            </template>
          </div>

          <!-- 成员两行制：行1 身份（拖拽/序号/名称/状态/移除），行2 配置（数据集+取行/传参）。
               combo 拖拽仅影响记录生成序；chain 顺序即执行顺序（行间连接线可视化） -->
          <div v-if="items.length" ref="listRef" class="member-list" :class="{ chain: mode === 'chain' }">
            <template v-for="(m, i) in items" :key="m.case_id + '-' + i">
              <div class="member-item">
                <div class="member-line">
                  <el-tooltip :content="mode === 'chain' ? '拖拽排序（上游 → 下游）' : '拖拽排序'" placement="top" popper-class="app-tip">
                    <el-icon class="drag-handle"><Rank /></el-icon>
                  </el-tooltip>
                  <span class="member-order">{{ i + 1 }}</span>
                  <span class="member-name" :title="m.case_name">{{ m.case_name || `用例#${m.case_id}` }}</span>
                  <el-tag size="small" effect="plain" type="info">{{ projectName(m.project_id) }}</el-tag>
                  <el-tag v-if="m.case_missing" size="small" type="danger">用例已删除</el-tag>
                  <el-tag v-else-if="!m.env_id" size="small" type="danger">环境未绑定</el-tag>
                  <el-button link type="danger" size="small" @click="removeItem(i)">移除</el-button>
                </div>
                <div v-if="!m.case_missing" class="member-config">
                  <!-- 数据集覆盖（与取行解耦：覆盖数据集 + 每轮顺移 也能表达） -->
                  <el-select
                    :model-value="m.dataset_id == null ? '' : m.dataset_id"
                    placeholder="用例默认绑定"
                    size="small"
                    style="width: 210px"
                    :loading="!dsInfo[m.case_id] && !dsError[m.case_id]"
                    @change="(v: any) => onPickDataset(m, v)"
                  >
                    <el-option value="" label="用例默认绑定" />
                    <el-option v-if="m.dataset_missing" :value="m.dataset_id" label="数据集已删除，请重选" disabled />
                    <el-option
                      v-for="d in dsInfo[m.case_id] || []"
                      :key="d.id"
                      :value="d.id"
                      :label="dsLabel(m, d)"
                      :disabled="!d.rows.length"
                    />
                  </el-select>
                  <el-button v-if="dsError[m.case_id]" link type="danger" size="small" @click="loadDsInfo(m, true)">
                    数据集加载失败 · 重试
                  </el-button>

                  <!-- 取行策略（两模式同一套语法）：自动 = chain 每轮顺移 / combo 固定首行；固定行 = 每次都用指定行 -->
                  <span class="cfg-label">取行</span>
                  <el-radio-group
                    :model-value="m.dataset_row_index == null ? 'auto' : 'pin'"
                    size="small"
                    @change="(v: any) => onRowPolicy(m, v)"
                  >
                    <el-radio-button value="auto">{{ mode === 'chain' ? '每轮顺移' : '首行' }}</el-radio-button>
                    <el-radio-button value="pin">固定行</el-radio-button>
                  </el-radio-group>
                  <el-select
                    v-if="m.dataset_row_index != null"
                    :model-value="m.dataset_row_index"
                    size="small"
                    style="width: 170px"
                    placeholder="选择行"
                    @change="(v: any) => onPickRow(m, v)"
                  >
                    <el-option v-for="r in memberRows(m)" :key="r.row_index" :value="r.row_index" :label="r.label || `第${r.row_index}行`" />
                    <el-option v-if="!memberRows(m).length" :value="m.dataset_row_index" label="（无数据行）" disabled />
                  </el-select>
                  <template v-if="mode !== 'chain'">
                    <span class="cfg-label">次数</span>
                    <el-input-number v-model="m.run_count" :min="1" :max="9999" size="small" style="width: 96px" controls-position="right" @change="dirty = true" />
                  </template>

                  <!-- chain 相邻定向传参：本成员成功后按名单把输出变量传给下一棒（末棒无下游） -->
                  <el-select
                    v-if="mode === 'chain' && i < items.length - 1"
                    v-model="m.pass_vars"
                    multiple filterable allow-create default-first-option
                    :reserve-keyword="false"
                    placeholder="成功后传给下一棒的变量，回车添加"
                    size="small"
                    class="cfg-pass"
                    @change="dirty = true"
                  />
                </div>
              </div>
              <div v-if="mode === 'chain' && i < items.length - 1" class="chain-link">
                <el-icon><ArrowDown /></el-icon>
              </div>
            </template>
          </div>
          <EmptyState v-else :image-size="70" description="暂无成员">
            <el-button type="primary" @click="addVisible = true">添加成员</el-button>
          </EmptyState>
        </el-card>

        <!-- 定时执行：未配置只留一行入口；已配置折叠为摘要行，点「编辑」才展开单行表单 -->
        <el-card shadow="never" class="schedule-card">
          <template #header>
            <div class="card-head">
              <div class="head-title">
                <span>定时执行</span>
                <el-tooltip content="保存后由调度器接管；上轮未结束自动跳过，错过 60s 不补跑" placement="top" popper-class="app-tip">
                  <el-icon class="strip-help"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div class="schedule-head-right">
                <template v-if="scheduleConfigured">
                  <span class="schedule-summary">{{ scheduleSummaryText }}</span>
                  <el-tag v-if="plan.next_run_at && scheduleEnabled" size="small" effect="plain" type="info">
                    下次 {{ formatTime(plan.next_run_at) }}
                  </el-tag>
                  <el-tooltip :content="switchTip" placement="top" popper-class="app-tip">
                    <el-switch
                      :model-value="!!plan.schedule_type && scheduleEnabled"
                      :disabled="!plan.schedule_type"
                      size="small"
                      @change="onToggleSchedule"
                    />
                  </el-tooltip>
                  <el-button link type="primary" size="small" @click="scheduleEditing = !scheduleEditing">
                    {{ scheduleEditing ? '收起' : '编辑' }}
                  </el-button>
                  <el-button v-if="plan.schedule_type" link type="danger" size="small" @click="onClearSchedule">清除</el-button>
                </template>
                <el-button v-else link type="primary" size="small" @click="onStartScheduleConfig">＋ 配置定时</el-button>
              </div>
            </div>
          </template>
          <div v-if="scheduleConfigured && scheduleEditing" class="schedule-form">
            <el-radio-group v-model="scheduleType" size="small" @change="onScheduleTouched">
              <el-radio-button value="interval">间隔执行</el-radio-button>
              <el-radio-button value="daily">每日定时</el-radio-button>
            </el-radio-group>
            <template v-if="scheduleType === 'interval'">
              <el-input-number v-model="scheduleMinutes" :min="1" :max="525600" size="small" controls-position="right" style="width: 110px" @change="onScheduleTouched" />
              <span class="strip-label">分钟</span>
            </template>
            <el-time-picker v-else v-model="scheduleDaily" format="HH:mm" value-format="HH:mm" size="small" placeholder="08:30" style="width: 110px" @change="onScheduleTouched" />
          </div>
          <div v-else-if="!scheduleConfigured" class="schedule-empty">未配置 —— 方案仅手动执行</div>
        </el-card>
      </template>
    </div>

    <!-- 执行确认：chain=轮数选择（全部 sheet/自定义，覆盖仅本次）；combo=成员/记录数摘要 -->
    <PlanExecuteDialog v-model="executeVisible" :plan="plan" @confirm="onExecuteConfirm" />
    <!-- 添加成员：项目 → 分组勾选 + 搜索，一次可加多个 -->
    <PlanMemberAddDialog
      v-model="addVisible"
      :exclude-case-ids="items.map((m) => m.case_id)"
      :default-project-id="store.currentProjectId"
      @confirm="onAddMembers"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import Sortable from 'sortablejs'
import { ArrowDown, ArrowLeft, Plus, QuestionFilled, Rank, WarningFilled } from '@element-plus/icons-vue'
import { caseApi, planApi, type TestCase } from '@/api'
import { useAppStore } from '@/stores'
import { useTabStore } from '@/stores/tabs'
import { useExecutionRunner } from '@/composables/useExecutionRunner'
import { formatTime } from '@/utils/format'
import EmptyState from '@/components/EmptyState.vue'
import PlanExecuteDialog from '@/components/PlanExecuteDialog.vue'
import PlanMemberAddDialog from '@/components/PlanMemberAddDialog.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const tabStore = useTabStore()
const runner = useExecutionRunner()

const planId = Number(route.params.id)
const plan = ref<Awaited<ReturnType<typeof planApi.get>> | null>(null)
const loading = ref(false)
const loadError = ref('')
const dirty = ref(false)
const saving = ref(false)
const running = ref(false)
const executeVisible = ref(false) // 执行确认弹窗（chain=轮数选择 / combo=摘要）
const addVisible = ref(false)     // 添加成员弹窗

const name = ref('')
const description = ref('')
const concurrency = ref(4)
// 方案模式：combo 并行组合 / chain 串行链（按序+相邻定向传参+失败阻断本轮下游）
const mode = ref<'combo' | 'chain'>('combo')
// chain 专用：整链轮数（轮内串行、轮间按 concurrency 并行）；combo 恒 1
const rounds = ref(1)

// 内嵌定时本地态（保存时随基础字段一并提交；清除走 schedule_off）
const scheduleType = ref<'interval' | 'daily'>('interval')
const scheduleMinutes = ref(30)
const scheduleDaily = ref('08:00')
const scheduleEnabled = ref(true)
// 本次编辑是否动过定时表单：决定保存时是否提交定时四件套
// （未配置的方案不得因普通保存被隐式配上默认 30 分钟定时；清除后不得随保存复活）
const scheduleTouched = ref(false)
// 定时表单展开态：已配置时默认折叠成摘要行，点「编辑」才展开
const scheduleEditing = ref(false)

// 是否处于「已配置（或本次正在配置）」态：未配置时整卡只留一行入口
const scheduleConfigured = computed(() => !!plan.value?.schedule_type || scheduleTouched.value)

// 摘要文案反映本地值（编辑未保存也能实时预览）
const scheduleSummaryText = computed(() => {
  const base = scheduleType.value === 'interval' ? `每 ${scheduleMinutes.value} 分钟` : `每日 ${scheduleDaily.value}`
  return plan.value?.schedule_type && !scheduleEnabled.value ? `已停用 · ${base}` : base
})

const switchTip = computed(() => !plan.value?.schedule_type
  ? '尚未保存定时配置：先编辑并保存，之后可在此开关'
  : scheduleEnabled.value
    ? '停用后调度器跳过本轮（配置保留）· 保存后生效'
    : '开启后由调度器接管定时执行 · 保存后生效')

function onScheduleTouched() {
  scheduleTouched.value = true
  dirty.value = true
}

function onStartScheduleConfig() {
  scheduleTouched.value = true
  scheduleEditing.value = true
  dirty.value = true
}

function onToggleSchedule(v: string | number | boolean) {
  scheduleEnabled.value = !!v
  onScheduleTouched()
}

// 本地成员行（保存时整体替换提交）；env/project 信息由 caseApi.get 补全展示
interface ItemRow {
  case_id: number
  case_name: string
  project_id: number | null
  env_id: number | null
  dataset_id: number | null
  case_dataset_id: number | null  // 用例自身绑定（dataset_id 空时实际生效）
  dataset_row_index: number | null
  run_count: number
  pass_vars: string[]              // chain：传给下一棒的输出变量名单（末棒空）
  case_missing: boolean
  dataset_missing: boolean
}
const items = ref<ItemRow[]>([])

function projectName(pid: number | null): string {
  if (pid == null) return '未知项目'
  return store.projects.find(p => p.id === pid)?.name || `项目#${pid}`
}

// ===== 数据集选项（成员加载/添加时并行预取；数据集与取行两个控件共享） =====
interface DsInfo { id: number; name: string; rows: { row_index: number; label: string }[] }
const dsInfo = ref<Record<number, DsInfo[]>>({})
const dsError = ref<Record<number, boolean>>({})

async function loadDsInfo(m: ItemRow, force = false) {
  if (m.case_missing) return
  if (!force && (dsInfo.value[m.case_id] || dsError.value[m.case_id])) return
  dsError.value[m.case_id] = false
  try {
    const list = await caseApi.datasets(m.case_id)
    dsInfo.value[m.case_id] = list.map((d) => ({
      id: d.id,
      name: d.name,
      rows: d.rows.map((r) => ({ row_index: r.row_index, label: r.label || '' })),
    }))
  } catch {
    dsInfo.value[m.case_id] = []
    dsError.value[m.case_id] = true
  }
}

/** 成员生效数据集的全部数据行（覆盖 > 用例绑定） */
function memberRows(m: ItemRow): { row_index: number; label: string }[] {
  const eff = m.dataset_id ?? m.case_dataset_id
  if (eff == null) return []
  return dsInfo.value[m.case_id]?.find((d) => d.id === eff)?.rows || []
}

/** 选项直接带行数（选中后闭着也能看到数据量；空数据集不可选） */
function dsLabel(m: ItemRow, d: DsInfo): string {
  if (!d.rows.length) return `${d.name}（空）`
  const bound = d.id === m.case_dataset_id ? ' · 用例绑定' : ''
  return `${d.name} · ${d.rows.length} 行${bound}`
}

function onPickDataset(m: ItemRow, v: any) {
  m.dataset_id = v === '' || v == null ? null : Number(v)
  m.dataset_missing = false
  // 固定 sheet 跟随新数据集校验：不存在则回落到首个 sheet（或顺移）
  if (m.dataset_row_index != null) {
    const rows = memberRows(m)
    if (!rows.some((r) => r.row_index === m.dataset_row_index)) {
      m.dataset_row_index = rows.length ? rows[0].row_index : null
    }
  }
  dirty.value = true
}

/** 取行策略（两模式同语法）：auto=row 置空（chain 每轮顺移 / combo 固定首行）；pin=固定到首个数据行 */
function onRowPolicy(m: ItemRow, v: any) {
  if (v === 'pin') {
    const rows = memberRows(m)
    if (!rows.length) {
      ElMessage.warning('该数据集暂无数据行，无法固定')
      return
    }
    m.dataset_row_index = rows[0].row_index
  } else {
    m.dataset_row_index = null
  }
  dirty.value = true
}

function onPickRow(m: ItemRow, v: any) {
  m.dataset_row_index = Number(v)
  dirty.value = true
}

// ===== 加载 =====
async function load() {
  if (!planId) return
  loading.value = true
  loadError.value = ''
  try {
    plan.value = await planApi.get(planId)
    name.value = plan.value.name
    description.value = plan.value.description || ''
    concurrency.value = plan.value.concurrency
    mode.value = plan.value.mode || 'combo'
    rounds.value = plan.value.rounds || 1
    scheduleType.value = plan.value.schedule_type || 'interval'
    scheduleMinutes.value = plan.value.schedule_interval_minutes || 30
    scheduleDaily.value = plan.value.schedule_daily_time || '08:00'
    scheduleEnabled.value = plan.value.schedule_enabled
    scheduleTouched.value = false
    scheduleEditing.value = false
    // 成员行回填 + caseApi.get 补全 env/project 展示（并行，成员数通常个位数）
    items.value = await Promise.all(plan.value.items.map(async (it) => {
      const base: ItemRow = {
        case_id: it.case_id, case_name: it.case_name || '',
        project_id: null, env_id: null,
        dataset_id: it.dataset_id ?? null, dataset_row_index: it.dataset_row_index ?? null,
        case_dataset_id: it.case_dataset_id ?? null,
        run_count: it.run_count || 1,
        pass_vars: it.pass_vars || [],
        case_missing: !!it.case_missing, dataset_missing: !!it.dataset_missing,
      }
      if (base.case_missing) return base
      try {
        const c = await caseApi.get(it.case_id)
        base.case_name = c.name
        base.project_id = c.project_id
        base.env_id = c.env_id ?? null
        base.case_dataset_id = c.dataset_id ?? null
      } catch { /* 用例详情取失败不阻塞编辑（执行预检兜底） */ }
      return base
    }))
    dirty.value = false
    // 数据集选项并行预取（两个取行控件共享；成员数个位数）
    items.value.forEach((m) => { loadDsInfo(m) })
    nextTick(initSortable)
  } catch (e: any) {
    loadError.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// ===== 拖拽排序（draggable 限定成员块——chain 行间的连接线节点不参与计数） =====
const listRef = ref<HTMLElement | null>(null)
let sortable: Sortable | null = null

function initSortable() {
  destroySortable()
  if (!listRef.value) return
  sortable = Sortable.create(listRef.value, {
    handle: '.drag-handle',
    draggable: '.member-item',
    animation: 200,
    ghostClass: 'sortable-ghost',
    onEnd: (evt: any) => {
      const { oldIndex, newIndex } = evt
      if (oldIndex == null || newIndex == null || oldIndex === newIndex) return
      const arr = items.value
      const [moved] = arr.splice(oldIndex, 1)
      arr.splice(newIndex, 0, moved)
      dirty.value = true
    },
  })
}
function destroySortable() {
  if (sortable) { sortable.destroy(); sortable = null }
}

// ===== 添加成员（弹窗多选，confirm 返回选中的用例对象） =====
function onAddMembers(cases: TestCase[]) {
  const exist = new Set(items.value.map((m) => m.case_id))
  const fresh = cases.filter((c) => !exist.has(c.id))
  for (const c of fresh) {
    const row: ItemRow = {
      case_id: c.id, case_name: c.name,
      project_id: c.project_id ?? null, env_id: c.env_id ?? null,
      dataset_id: null, dataset_row_index: null, case_dataset_id: c.dataset_id ?? null,
      run_count: 1, pass_vars: [],
      case_missing: false, dataset_missing: false,
    }
    items.value.push(row)
    loadDsInfo(row)
  }
  if (fresh.length) {
    dirty.value = true
    ElMessage.success(`已添加 ${fresh.length} 个成员`)
  }
}

function removeItem(i: number) {
  items.value.splice(i, 1)
  dirty.value = true
}

// ===== 保存（基础 + 定时一并提交，成员整体替换） =====
async function onSave(silent = false) {
  if (!name.value.trim()) return ElMessage.warning('请输入方案名称')
  saving.value = true
  try {
    plan.value = await planApi.update(planId, {
      name: name.value.trim(),
      description: description.value,
      concurrency: concurrency.value,
      mode: mode.value,
      // chain 整链轮数随模式提交（combo 恒 1）
      rounds: mode.value === 'chain' ? rounds.value : 1,
      // 已配置或本次动过定时才提交四件套：未配置不得隐式配上默认定时，清除后不得随保存复活
      ...(plan.value?.schedule_type || scheduleTouched.value
        ? {
            schedule_type: scheduleType.value,
            schedule_interval_minutes: scheduleType.value === 'interval' ? scheduleMinutes.value : null,
            schedule_daily_time: scheduleType.value === 'daily' ? scheduleDaily.value : null,
            schedule_enabled: scheduleEnabled.value,
          }
        : {}),
    })
    plan.value = await planApi.updateItems(planId, items.value.map((m, i) => ({
      case_id: m.case_id,
      dataset_id: m.dataset_id,
      dataset_row_index: m.dataset_row_index,
      run_count: m.run_count,
      pass_vars: m.pass_vars,
      sort_order: i,
    })))
    dirty.value = false
    if (!silent) ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
    throw e
  } finally {
    saving.value = false
  }
}

// 清除定时：schedule_off 显式语义（schedule_type=null 在局部更新里表示「未提供」）
async function onClearSchedule() {
  try {
    await planApi.update(planId, { schedule_off: true })
    // 本地表单一并复位，防后续普通保存让定时以默认值复活
    scheduleType.value = 'interval'
    scheduleMinutes.value = 30
    scheduleDaily.value = '08:00'
    scheduleEnabled.value = plan.value?.schedule_enabled ?? true
    scheduleTouched.value = false
    scheduleEditing.value = false
    await load()
    ElMessage.success('已清除定时')
  } catch (e: any) {
    ElMessage.error(e.message || '清除失败')
  }
}

// ===== 一键执行：先落盘未保存的编辑，再弹执行确认（chain=轮数选择 / combo=摘要） =====
async function onExecute() {
  if (!items.value.length) return ElMessage.warning('请先添加成员用例')
  if (running.value) return
  try {
    if (dirty.value) await onSave(true)
  } catch {
    return // 保存失败已在 onSave 内提示
  }
  if (!plan.value) return
  executeVisible.value = true
}

// 执行弹窗确认：chain 带 rounds（本次覆盖，不落库）；combo 不带
async function onExecuteConfirm({ rounds }: { rounds?: number }) {
  await startRun(rounds)
}

async function startRun(rounds?: number) {
  running.value = true
  try {
    await runner.runPlanWithFeedback(planId, name.value, rounds != null ? { rounds } : {})
    await load() // 回写 last_run_at/next_run_at
  } catch (e: any) {
    ElMessage.error(e.message || '执行失败')
  } finally {
    running.value = false
  }
}

// ===== 未保存改动防丢失（与其余编辑器对齐） =====
watch(dirty, (v) => tabStore.setDirty(route.path, v ? '方案编辑' : null), { immediate: true })

const onBeforeUnload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}
function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    onSave()
  }
}
onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('keydown', onKeydown)
})

onMounted(load)
onUnmounted(destroySortable)
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--app-bg);
}
.edit-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.member-card,
.schedule-card {
  background: var(--app-card);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.member-count {
  font-size: 12px;
  color: var(--app-text-muted);
}
/* 执行设置：模式 + 模式相关参数 + 描述 */
.settings-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: var(--app-radius-sm);
}
.strip-label {
  font-size: 12px;
  color: var(--app-text-muted);
  white-space: nowrap;
}
.strip-help {
  color: var(--app-text-faint);
  font-size: 14px;
  cursor: help;
  flex-shrink: 0;
}
.strip-desc {
  flex: 1;
  min-width: 180px;
}
/* 模式语义常显一行（短句；此前藏 ? 提示导致语义不可见） */
.mode-hint {
  font-size: 12px;
  color: var(--app-text-faint);
  line-height: 1.5;
  margin: 8px 2px 12px;
}
/* 成员列表：两行制（身份行 + 配置行） */
.member-list {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  max-height: 480px;
  overflow-y: auto;
}
.member-item {
  background: var(--el-bg-color);
}
.member-item:hover {
  background: var(--app-hover);
}
.member-list:not(.chain) .member-item + .member-item {
  border-top: 1px solid var(--app-border);
}
.drag-handle {
  cursor: grab;
  color: var(--app-text-muted);
  font-size: 16px;
  flex-shrink: 0;
}
.drag-handle:active {
  cursor: grabbing;
}
.sortable-ghost {
  opacity: 0.4;
  background: var(--app-active) !important;
}
.member-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px 3px;
}
.member-order {
  width: 20px;
  height: 20px;
  line-height: 20px;
  border-radius: 50%;
  background: var(--el-fill-color);
  text-align: center;
  font-size: 11px;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.member-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
/* chain 顺序连接线（上游 → 下游的可视化；combo 不渲染） */
.chain-link {
  display: flex;
  align-items: center;
  margin-left: 42px;
  height: 18px;
  color: var(--app-text-faint);
  font-size: 12px;
}
.member-config {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
  padding: 2px 12px 9px 68px;
}
.cfg-label {
  font-size: 12px;
  color: var(--app-text-muted);
  white-space: nowrap;
}
.cfg-pass {
  width: 250px;
}
/* 定时卡：未配置一行入口；已配置摘要行 + 按需展开的编辑行 */
.schedule-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.schedule-summary {
  font-size: 13px;
  color: var(--app-text);
}
.schedule-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.schedule-empty {
  font-size: 12px;
  color: var(--app-text-faint);
}
</style>
