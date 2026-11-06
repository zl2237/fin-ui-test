<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { caseApi, planApi, type ExecutionPlan, type PlanItem } from '@/api'

/**
 * 执行方案确认弹窗（chain / combo 两分支）：
 * - chain 串行链：只问「本次轮数」——单个数字输入，打开时按成员数据集最大行数预填
 *   （每轮各成员自动取下一行，固定行的成员不变；成员未绑数据集则取方案默认轮数）。
 *   覆盖仅本次生效（POST /plans/{id}/execute body.rounds），不回写方案配置。
 * - combo 并行组合：成员/数据集/预计记录数摘要（Σrun_count），无轮数概念。
 * 只做确认 UI——确认后 emit('confirm', { rounds? }) 并自关，执行编排由父视图完成
 * （BatchRunDialog 同款契约；combo 的 rounds 为 undefined=不覆盖）。
 */
const props = defineProps<{
  modelValue: boolean
  /** 待执行的方案行（列表/编辑页传入；打开时自取详情与各成员 sheet 数） */
  plan: ExecutionPlan | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', payload: { rounds?: number }): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const loadError = ref('')
const items = ref<PlanItem[]>([])
/** 成员行展示态：sheet 数（数据集缺失=null）、是否固定行、执行次数 */
interface MemberStat {
  name: string
  datasetName: string
  sheets: number | null
  pinned: number | null
  runCount: number
}
const stats = ref<MemberStat[]>([])

const isChain = computed(() => (props.plan?.mode || 'combo') === 'chain')
const dialogTitle = computed(() => (isChain.value ? '执行方案（串行链）' : '执行方案（并行组合）'))

/** 本次轮数（打开时按数据集最大行数预填，可改；仅本次生效） */
const rounds = ref(1)

/** 数据集最大行数 = 各成员生效数据集的最大行数（未绑数据集的成员按 0 计） */
const maxSheets = computed(() => Math.max(0, ...stats.value.map((s) => s.sheets ?? 0)))
const pinnedMembers = computed(() =>
  stats.value.filter((s) => s.pinned !== null).map((s) => s.name))
/** combo 预计记录数 = Σ 各成员 run_count */
const totalRecords = computed(() =>
  stats.value.reduce((n, s) => n + (s.runCount || 1), 0))

watch(() => props.modelValue, async (open) => {
  if (!open || !props.plan) return
  rounds.value = props.plan.rounds || 1
  loading.value = true
  loadError.value = ''
  stats.value = []
  try {
    const detail = await planApi.get(props.plan.id)
    items.value = detail.items
    // 各成员数据集 sheet 数：同用例的请求按 case_id 去重
    const dsCache = new Map<number, Awaited<ReturnType<typeof caseApi.datasets>>>()
    const out: MemberStat[] = []
    for (const it of detail.items) {
      const dsId = it.dataset_id ?? it.case_dataset_id ?? null
      let sheets: number | null = null
      if (dsId && !it.dataset_missing) {
        if (!dsCache.has(it.case_id)) {
          dsCache.set(it.case_id, await caseApi.datasets(it.case_id))
        }
        sheets = dsCache.get(it.case_id)!.find((d) => d.id === dsId)?.rows.length ?? null
      }
      out.push({
        name: it.case_missing ? `#${it.case_id}（用例已删）` : (it.case_name || `#${it.case_id}`),
        datasetName: it.dataset_missing
          ? `${it.dataset_name || '数据集'}（已删）`
          : (it.dataset_name || '（用例绑定/无）'),
        sheets,
        pinned: it.dataset_row_index ?? null,
        runCount: it.run_count || 1,
      })
    }
    stats.value = out
    // 有数据集按最大行数预填轮数（每轮取下一行 = 数据全量跑完）；否则保持方案默认轮数
    if (maxSheets.value) rounds.value = maxSheets.value
  } catch (e: any) {
    loadError.value = e?.message || '加载方案详情失败'
  } finally {
    loading.value = false
  }
})

function confirm() {
  // combo 无轮数概念：不带 rounds（父视图不传覆盖，后端按 plan.rounds=1 执行）
  if (isChain.value) emit('confirm', { rounds: rounds.value || 1 })
  else emit('confirm', {})
  visible.value = false
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="min(620px, 92vw)"
    align-center
    :close-on-click-modal="false"
  >
    <div v-if="plan" class="pe-tip">
      <template v-if="isChain">
        方案「{{ plan.name }}」共 {{ stats.length || plan.item_count }} 个成员，默认轮数
        {{ plan.rounds }} 轮，轮内按序串行 + 相邻传参 + 失败阻断本轮下游，轮间最多
        {{ plan.concurrency }} 轮并行。
      </template>
      <template v-else>
        方案「{{ plan.name }}」共 {{ stats.length || plan.item_count }} 个成员，各成员独立并行执行
        （失败互不影响），并发为提交上限（最多 {{ plan.concurrency }} 个同时执行）。
      </template>
    </div>

    <div v-loading="loading" class="pe-body">
      <div v-if="loadError" class="pe-err">{{ loadError }}</div>
      <template v-else>
        <div class="pe-members">
          <div v-for="s in stats" :key="s.name" class="pe-member">
            <span class="pe-member-name" :title="s.name">{{ s.name }}</span>
            <span class="pe-member-ds" :title="s.datasetName">{{ s.datasetName }}</span>
            <span class="pe-member-sheets">
              <template v-if="isChain">
                {{ s.sheets === null ? '—' : `${s.sheets} 行` }}
                <template v-if="s.pinned !== null">· 固定第 {{ s.pinned }} 行</template>
              </template>
              <template v-else>
                {{ s.pinned !== null ? `固定第 ${s.pinned} 行` : '首行' }} · × {{ s.runCount }}
              </template>
            </span>
          </div>
        </div>

        <div v-if="isChain" class="pe-rounds">
          <div class="pe-rounds-line">
            <span class="pe-rounds-label">本次轮数</span>
            <el-input-number v-model="rounds" :min="1" :max="9999" size="small" />
          </div>
          <div class="pe-rounds-note">
            <template v-if="maxSheets">
              已按成员数据集最大行数（{{ maxSheets }} 行）预填——每轮各成员自动取下一行，固定行的成员不变
            </template>
            <template v-else>
              成员未绑数据集，已按方案默认轮数预填
            </template>
            ；改动仅本次生效，不修改方案配置
          </div>
        </div>

        <div v-if="isChain && pinnedMembers.length" class="pe-warn">
          成员「{{ pinnedMembers.join('、') }}」固定行，每轮不变（不随轮次推进）。
        </div>
      </template>
    </div>

    <template #footer>
      <span v-if="isChain" class="pe-total">本次 {{ rounds || 1 }} 轮 × {{ stats.length || plan?.item_count || 0 }} 个成员</span>
      <span v-else class="pe-total">本次共 {{ totalRecords }} 条执行记录 · 并发 {{ plan?.concurrency ?? 1 }}</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="success" :disabled="!!loadError || loading" @click="confirm">开始执行</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.pe-tip {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-bottom: 10px;
  line-height: 1.5;
}
.pe-body { min-height: 90px; }
.pe-err {
  font-size: 13px;
  color: var(--el-color-danger);
  padding: 16px 4px;
}
.pe-members {
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: 2px 12px;
  margin-bottom: 12px;
}
.pe-member {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
}
.pe-member + .pe-member { border-top: 1px solid var(--app-border); }
.pe-member-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pe-member-ds {
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-muted);
  font-size: 12px;
}
.pe-member-sheets {
  white-space: nowrap;
  color: var(--app-text-muted);
  font-size: 12px;
}
.pe-rounds { margin-bottom: 4px; }
.pe-rounds-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.pe-rounds-label {
  font-size: 13px;
}
.pe-rounds-note {
  font-size: 12px;
  color: var(--app-text-faint);
  line-height: 1.5;
}
.pe-warn {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-color-warning);
  line-height: 1.5;
}
.pe-total {
  float: left;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 32px;
}
</style>
