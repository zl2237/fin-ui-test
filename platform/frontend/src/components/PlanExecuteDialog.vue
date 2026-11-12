<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { caseApi, planApi, type ExecutionPlan, type PlanItem } from '@/api'

/**
 * 执行方案确认弹窗（并行组合，B3 删链后唯一模式）：
 * 成员/数据集/sheet/预计记录数摘要，无轮数与传参概念。
 * 每成员记录数 = Σ(选中/绑定数据集 sheet 数) × run_count；成员相互独立并行，
 * 并发为提交上限（UI 用例另受浏览器槽位闸门约束）。
 * 只做确认 UI——确认后 emit('confirm') 并自关，执行编排由父视图完成。
 */
const props = defineProps<{
  modelValue: boolean
  /** 待执行的方案行（列表/编辑页传入；打开时自取详情与各成员数据集 sheet 数） */
  plan: ExecutionPlan | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const loadError = ref('')
const items = ref<PlanItem[]>([])
/** 成员行展示态：数据集清单（每项含 sheet 数）与执行次数 */
interface MemberDs {
  name: string
  sheets: number | null   // null=数据集已删（执行预检会拦下）
  missing: boolean
}
interface MemberStat {
  name: string
  datasets: MemberDs[]
  /** 数据集未加载到（归属变更/网络失败）时保底显示 */
  datasetMissing: boolean
  runCount: number
}
const stats = ref<MemberStat[]>([])

/** 预计记录数 = Σ 成员 Σ(数据集 sheet 数) × run_count */
const totalRecords = computed(() => stats.value.reduce((n, s) =>
  n + s.datasets.reduce((k, d) => k + (d.sheets ?? 0), 0) * (s.runCount || 1), 0))

watch(() => props.modelValue, async (open) => {
  if (!open || !props.plan) return
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
      // 生效集 = 成员选中（dataset_ids）> 用例自身 bound 集（case_dataset_ids）
      const eff = it.dataset_ids?.length ? it.dataset_ids : (it.case_dataset_ids || [])
      const names = it.dataset_ids?.length ? (it.dataset_names || []) : []
      const datasets: MemberDs[] = []
      if (!it.case_missing && !it.dataset_missing) {
        if (!dsCache.has(it.case_id)) {
          dsCache.set(it.case_id, await caseApi.datasets(it.case_id))
        }
        const dsList = dsCache.get(it.case_id)!
        for (const id of eff) {
          const ds = dsList.find((d) => d.id === id)
          datasets.push({
            name: ds?.name || names[eff.indexOf(id)] || `#${id}`,
            sheets: ds ? ds.rows.length : null,
            missing: !ds,
          })
        }
      }
      out.push({
        name: it.case_missing ? `#${it.case_id}（用例已删）` : (it.case_name || `#${it.case_id}`),
        datasets,
        datasetMissing: !!it.dataset_missing,
        runCount: it.run_count || 1,
      })
    }
    stats.value = out
  } catch (e: any) {
    loadError.value = e?.message || '加载方案详情失败'
  } finally {
    loading.value = false
  }
})

function confirm() {
  emit('confirm')
  visible.value = false
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="执行方案（并行组合）"
    width="min(620px, 92vw)"
    align-center
    :close-on-click-modal="false"
  >
    <div v-if="plan" class="pe-tip">
      方案「{{ plan.name }}」共 {{ stats.length || plan.item_count }} 个成员，各成员独立并行执行
      （失败互不影响），并发为提交上限（最多 {{ plan.concurrency }} 个同时提交；UI 用例另受浏览器槽位约束）。
      每成员记录数 = 选中/绑定数据集 × 全部 sheet × 次数。
    </div>

    <div v-loading="loading" class="pe-body">
      <div v-if="loadError" class="pe-err">{{ loadError }}</div>
      <template v-else>
        <div class="pe-members">
          <div v-for="s in stats" :key="s.name" class="pe-member">
            <span class="pe-member-name" :title="s.name">{{ s.name }}</span>
            <span class="pe-member-ds" :title="s.datasets.map((d) => d.name).join('、')">
              <template v-if="s.datasetMissing">数据集悬空，请先编辑方案</template>
              <template v-else-if="!s.datasets.length">（未绑数据集，不可执行）</template>
              <template v-else>{{ s.datasets.map((d) => `${d.name}${d.sheets == null ? '（已删）' : ` ${d.sheets} sheet`}`).join('、') }}</template>
            </span>
            <span class="pe-member-sheets">× {{ s.runCount }}</span>
          </div>
        </div>
      </template>
    </div>

    <template #footer>
      <span class="pe-total">本次共 {{ totalRecords }} 条执行记录 · 并发 {{ plan?.concurrency ?? 1 }}</span>
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
  max-height: 220px;
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
  flex-shrink: 0;
  max-width: 32%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pe-member-ds {
  flex: 1;
  min-width: 0;
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
.pe-total {
  float: left;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 32px;
}
</style>
