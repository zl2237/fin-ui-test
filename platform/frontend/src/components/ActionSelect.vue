<template>
  <el-select :model-value="value" filterable :placeholder="placeholder" @update:model-value="onChange">
    <!-- 可选内置动作（滤裸 custom：项目自定义分组已覆盖新建；存量裸 custom 走 ghost 回显） -->
    <el-option
      v-for="a in selectable"
      :key="a.action"
      :label="`${a.name}（${a.action}）`"
      :value="a.action"
    >
      <div class="action-opt" :title="docText(a)">
        <span class="action-opt-name">{{ a.name }}</span>
        <span class="action-opt-code">{{ a.action }}</span>
        <span class="action-opt-tag" :class="`origin-${a.origin}`">{{ UI_ACTION_ORIGINS[a.origin].label }}</span>
      </div>
    </el-option>
    <!-- 存量已下线动作（retired）：仅当前值命中时渲染（回显中文名），禁选不可再指定 -->
    <el-option
      v-for="a in ghostRetired"
      :key="`ghost-${a.action}`"
      :value="a.action"
      :label="`${a.name}（${a.action}）`"
      disabled
    >
      <div class="action-opt">
        <span class="action-opt-name">{{ a.name }}</span>
        <span class="action-opt-code">{{ a.action }}</span>
        <span class="action-opt-tag origin-retired">已下线</span>
      </div>
    </el-option>
    <!-- 裸 custom 回显（custom_id 缺失或模板已删的存量步骤）：引导改选下方模板或换动作 -->
    <el-option
      v-if="value === 'custom'"
      value="custom"
      label="自定义动作（custom）"
      disabled
    >
      <div class="action-opt" title="绑定模板不存在或未选，请在「项目自定义」组重选模板">
        <span class="action-opt-name">自定义动作</span>
        <span class="action-opt-code">custom</span>
        <span class="action-opt-tag origin-wrapped">未绑模板</span>
      </div>
    </el-option>
    <!-- 项目自定义动作（JS 模板）直列下拉：一步选中，免去先选 custom 再选模板 -->
    <el-option-group v-if="customActions.length" label="项目自定义（动作库维护）">
      <el-option
        v-for="ca in customActions"
        :key="`@custom/${ca.id}`"
        :value="`@custom/${ca.id}`"
        :label="ca.description ? `${ca.name}（${firstLine(ca.description)}）` : ca.name"
      >
        <div class="action-opt">
          <span class="action-opt-name">{{ ca.name }}</span>
          <span class="action-opt-code">custom:{{ ca.id }}</span>
          <span class="action-opt-tag origin-wrapped">自定义</span>
        </div>
      </el-option>
    </el-option-group>
  </el-select>
</template>

<script setup lang="ts">
/**
 * 统一动作选择器（2026-11-05）：UiActionForm「动作类型」与 NodeConfigDrawer「+ 添加动作」共用。
 * 两种模式：
 * - 编辑态：传 model-value（动作码或 @custom/{id} 哨兵）+ @update:model-value，随步骤回显；
 * - 追加态：不传 model-value，传 auto-reset + @select——选中即发事件并清空回 placeholder，可连续添加。
 * 选 el-select 而非自管 popover：旧 popover 因 el-dropdown 在抽屉内的焦点陷阱而生，
 * 而 el-select 在同一抽屉内已被 UiActionForm 长期验证可用（焦点坑仅 el-dropdown）。
 */
import { computed, ref } from 'vue'
import type { CustomAction, UiActionDoc } from '@/api'
import { SELECTABLE_UI_ACTIONS, UI_ACTIONS, UI_ACTION_ORIGINS, type UiActionMeta } from '@/utils/ui'

const props = withDefaults(defineProps<{
  /** 编辑态绑定值：动作码或 @custom/{id} 哨兵；追加态不传 */
  modelValue?: string
  /** 项目 JS 模板清单（@custom/{id} 选项组数据源） */
  customActions?: CustomAction[]
  /** 项目级描述覆盖（动作库维护；选项 hover 与 label 同源） */
  actionDocs?: UiActionDoc[]
  placeholder?: string
  /** 追加态：选中即清空回 placeholder，支持连续添加 */
  autoReset?: boolean
}>(), { customActions: () => [], placeholder: '选择动作' })

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'select', v: string): void
}>()

/** 追加态本地值（autoReset 清空目标）；编辑态恒用 modelValue */
const inner = ref('')
const value = computed(() => props.modelValue ?? inner.value)

/** 可选内置动作：滤已下线与裸 custom（custom 新建一律走 @custom/{id} 分组） */
const selectable = computed(() => SELECTABLE_UI_ACTIONS.filter((a) => a.action !== 'custom'))
/** ghost 回显：仅当前值命中的已下线动作（否则永不出现在列表里） */
const ghostRetired = computed(() => UI_ACTIONS.filter((a) => a.retired && a.action === value.value))

function docText(a: UiActionMeta): string {
  return props.actionDocs?.find((d) => d.action_key === a.action)?.usage_text || a.desc
}

function onChange(v: string) {
  emit('update:modelValue', v)
  emit('select', v)
  if (props.autoReset) inner.value = ''
}

/** 多行描述取首行（下拉 label 单行展示） */
function firstLine(text?: string | null): string {
  return (text || '').split('\n')[0].slice(0, 30)
}
</script>

<style scoped>
/* 选项行：名称 + 标识 + 来源标签（自 UiActionForm 迁入，两处下拉同款视觉） */
.action-opt {
  display: flex;
  align-items: center;
  gap: 8px;
}
.action-opt-name {
  font-weight: 500;
}
.action-opt-code {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-faint);
}
.action-opt-tag {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1;
  padding: 3px 7px;
  border-radius: 8px;
}
.action-opt-tag.origin-native {
  color: #2563eb;
  background: rgba(37, 99, 235, 0.12);
}
.action-opt-tag.origin-wrapped {
  color: #b45309;
  background: rgba(180, 83, 9, 0.12);
}
/* 已下线 ghost / 未绑模板：灰色态 */
.action-opt-tag.origin-retired {
  color: #6b7280;
  background: rgba(107, 114, 128, 0.12);
}
</style>
