<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { caseApi, planApi, type ExecutionPlan, type PlanItem } from '@/api'

/**
 * 串行链（chain）执行确认弹窗：一键执行前的轮数选择。
 * - 「全部 sheet（M 轮）」：M = 成员数据集最大 sheet 数，本次执行轮数覆盖为 M
 *   （每轮依次取各成员的第 r 个 sheet，不足沿用末个）——批量数据的标准入口；
 * - 「自定义轮数」：手动指定 1~9999。
 * 覆盖仅本次生效（POST /plans/{id}/execute body.rounds），不回写方案配置。
 * 只做选择 UI——确认后 emit('confirm', { rounds }) 并自关，执行编排由父视图完成
 * （BatchRunDialog 同款契约）。
 */
const props = defineProps<{
  modelValue: boolean
  /** 待执行的方案行（列表/编辑页传入；打开时自取详情与各成员 sheet 数） */
  plan: ExecutionPlan | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', payload: { rounds: number }): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const loadError = ref('')
const items = ref<PlanItem[]>([])
/** 成员行展示态：sheet 数（数据集缺失=null）与是否固定行 */
interface MemberStat {
  name: string
  datasetName: string
  sheets: number | null
  pinned: number | null
}
const stats = ref<MemberStat[]>([])

const mode = ref<'all' | 'custom'>('all')
const customRounds = ref(1)

/** 全部 sheet = 各成员数据集的最大 sheet 数（未绑数据集的成员按 0 计） */
const maxSheets = computed(() => Math.max(0, ...stats.value.map((s) => s.sheets ?? 0)))
const pinnedMembers = computed(() =>
  stats.value.filter((s) => s.pinned !== null).map((s) => s.name))
const effectiveRounds = computed(() =>
  (mode.value === 'all' ? maxSheets.value : customRounds.value) || 1)

watch(() => props.modelValue, async (open) => {
  if (!open || !props.plan) return
  mode.value = 'all'
  customRounds.value = props.plan.rounds || 1
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
      })
    }
    stats.value = out
    if (!maxSheets.value) mode.value = 'custom' // 成员均未绑数据集：全部 sheet 无从谈起
  } catch (e: any) {
    loadError.value = e?.message || '加载方案详情失败'
  } finally {
    loading.value = false
  }
})

function confirm() {
  emit('confirm', { rounds: effectiveRounds.value })
  visible.value = false
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="执行方案（串行链）"
    width="min(620px, 92vw)"
    align-center
    :close-on-click-modal="false"
  >
    <div v-if="plan" class="pe-tip">
      方案「{{ plan.name }}」共 {{ stats.length || plan.item_count }} 个成员，配置轮数
      {{ plan.rounds }} 轮，轮内按序串行 + 相邻传参 + 失败阻断本轮下游，轮间最多
      {{ plan.concurrency }} 轮并行。本次轮数仅对本次执行生效，不修改方案配置。
    </div>

    <div v-loading="loading" class="pe-body">
      <div v-if="loadError" class="pe-err">{{ loadError }}</div>
      <template v-else>
        <div class="pe-members">
          <div v-for="s in stats" :key="s.name" class="pe-member">
            <span class="pe-member-name" :title="s.name">{{ s.name }}</span>
            <span class="pe-member-ds" :title="s.datasetName">{{ s.datasetName }}</span>
            <span class="pe-member-sheets">
              {{ s.sheets === null ? '—' : `${s.sheets} sheet` }}
              <template v-if="s.pinned !== null">· 固定第 {{ s.pinned }} 行</template>
            </span>
          </div>
        </div>

        <el-radio-group v-model="mode" class="pe-mode">
          <div class="pe-mode-row">
            <el-radio value="all" :disabled="!maxSheets">全部 sheet（{{ maxSheets }} 轮）</el-radio>
            <span class="pe-mode-hint">每轮依次取各成员数据集的第 r 个 sheet（不足沿用末个）</span>
          </div>
          <div class="pe-mode-row">
            <el-radio value="custom">自定义轮数</el-radio>
            <el-input-number
              v-model="customRounds" :min="1" :max="9999" size="small"
              :disabled="mode !== 'custom'"
            />
          </div>
        </el-radio-group>

        <div v-if="pinnedMembers.length" class="pe-warn">
          成员「{{ pinnedMembers.join('、') }}」固定取指定 sheet，每轮不变（不随轮次推进）。
        </div>
        <div v-if="!maxSheets && !loading && !loadError" class="pe-warn">
          成员均未绑定数据集，「全部 sheet」不可用，请自定义轮数。
        </div>
      </template>
    </div>

    <template #footer>
      <span class="pe-total">本次 {{ effectiveRounds }} 轮 × {{ stats.length || plan?.item_count || 0 }} 个成员</span>
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
.pe-mode { display: block; }
.pe-mode-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.pe-mode-hint {
  font-size: 12px;
  color: var(--app-text-faint);
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
