<script setup lang="ts">
/**
 * ZiwiQtyField — 数量字段
 *
 * 三件事，都是被现场踩出来的：
 * 1. **唤起数字键盘**：`inputmode="decimal"` + `type="text"`（`type="number"` 在部分手持机上不给小数点）；
 * 2. **单位右置且只读**：单位不进输入框 —— 否则 "300件" 会被后端当数字解析失败（UE §4.2）；
 * 3. **最多 3 位小数**：超位即时提示（不静默截断，截断等于用户以为录进去了）。
 *
 * 校验口径由 `txt.validation.*` 生成（`字段 + 问题`），本组件只负责判定与提示。
 *
 * 依据：UE §4.2「数值 + 单位」、§8「数字与单位」、UE-15；架构 §5.2。
 */
import { computed, ref, watch } from 'vue'
import { txt } from '@/config/uiText'

interface Props {
  /** 数值（空为 null，绝不用 0 冒充空 —— 0 是合法业务值） */
  modelValue: number | null
  label?: string
  /** 单位（只读右置），如 PCS / 件 / kg */
  unit?: string
  placeholder?: string
  /** 最少小数位（默认 0） */
  minDecimals?: number
  /** 最多小数位（默认 3，UE §8 硬要求） */
  decimals?: number
  min?: number
  max?: number
  disabled?: boolean
  required?: boolean
  /** 字段名，渲染成 data-field 供表单定位 */
  fieldName?: string
  /** 是否显示减号/加号（默认不显示：数量多为手输，步进按钮在小屏上抢空间） */
  stepper?: boolean
  /** 步进值 */
  step?: number
}

const props = withDefaults(defineProps<Props>(), {
  label: '',
  unit: '',
  placeholder: '请输入数量',
  minDecimals: 0,
  decimals: 3,
  min: undefined,
  max: undefined,
  disabled: false,
  required: false,
  fieldName: '',
  stepper: false,
  step: 1,
})

const emit = defineEmits<{
  'update:modelValue': [value: number | null]
  /** 校验不通过（超小数位 / 超范围），页面可用于顶部摘要 */
  invalid: [message: string | null]
}>()

/** 输入框内的文本（保留用户正在输入的 "1." 这类中间态，不能立即 parse 覆盖） */
const text = ref<string>(props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue))
const errorMessage = ref<string | null>(null)

watch(
  () => props.modelValue,
  (value) => {
    const next = value === null || value === undefined ? '' : String(value)
    // 只在外部值与当前文本语义不等时才回写，避免打字过程中被覆盖（例如输 "1.0"）
    if (next !== text.value && Number(next) !== Number(text.value)) {
      text.value = next
    }
  },
)

/** 单位展示（空则不渲染，绝不显示 "undefined"） */
const unitText = computed(() => props.unit || '')

/**
 * 校验并向上抛出值。
 * @param raw 输入框原文
 */
function commit(raw: string): void {
  const value = raw.trim()
  if (value === '') {
    errorMessage.value = null
    emit('update:modelValue', null)
    emit('invalid', null)
    return
  }

  const num = Number(value)
  if (!Number.isFinite(num)) {
    errorMessage.value = txt.validation.pattern(props.label || '数量', '数字')
    emit('invalid', errorMessage.value)
    return
  }

  // 小数位超限：不静默截断
  const dotIndex = value.indexOf('.')
  const decimalsUsed = dotIndex >= 0 ? value.length - dotIndex - 1 : 0
  if (decimalsUsed > props.decimals) {
    errorMessage.value = txt.validation.decimals(props.label || '数量', props.decimals)
    emit('invalid', errorMessage.value)
    return
  }

  if (props.min !== undefined && num < props.min) {
    errorMessage.value = txt.validation.min(props.label || '数量', props.min)
    emit('invalid', errorMessage.value)
    return
  }

  if (props.max !== undefined && num > props.max) {
    errorMessage.value = txt.validation.max(props.label || '数量', props.max)
    emit('invalid', errorMessage.value)
    return
  }

  errorMessage.value = null
  emit('update:modelValue', num)
  emit('invalid', null)
}

function onInput(value: string): void {
  // 只允许数字与一个小数点（中文输入法全角字符会被这里挡掉）
  const filtered = (value ?? '').replace(/[^\d.]/g, '')
  text.value = filtered
  commit(filtered)
}

function onStep(delta: number): void {
  if (props.disabled) return
  const current = Number(text.value)
  const base = Number.isFinite(current) ? current : 0
  const next = Number((base + delta * props.step).toFixed(props.decimals))
  text.value = String(next)
  commit(text.value)
}
</script>

<template>
  <div class="ziwi-qty-field" :data-field="fieldName || undefined">
    <div class="ziwi-qty-field__row">
      <van-button
        v-if="stepper"
        class="ziwi-qty-field__step"
        plain
        :disabled="disabled"
        @click="onStep(-1)"
      >
        <van-icon name="minus" />
      </van-button>

      <van-field
        class="ziwi-qty-field__field"
        :model-value="text"
        :label="label"
        :placeholder="placeholder"
        :disabled="disabled"
        :required="required"
        type="text"
        inputmode="decimal"
        autocomplete="off"
        @update:model-value="onInput"
      />

      <span v-if="unitText" class="ziwi-qty-field__unit">{{ unitText }}</span>

      <van-button
        v-if="stepper"
        class="ziwi-qty-field__step"
        plain
        :disabled="disabled"
        @click="onStep(1)"
      >
        <van-icon name="plus" />
      </van-button>
    </div>
    <p v-if="errorMessage" class="ziwi-qty-field__error" role="alert" aria-live="polite">
      <van-icon name="warning-o" />
      <span>{{ errorMessage }}</span>
    </p>
  </div>
</template>

<style scoped>
.ziwi-qty-field {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.ziwi-qty-field__row {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  width: 100%;
  min-width: 0;
}

.ziwi-qty-field__field {
  flex: 1 1 auto;
  min-width: 0;
  padding-left: 0;
  padding-right: 0;
}

.ziwi-qty-field :deep(.van-field__body) {
  min-height: var(--ziwi-touch-min);
  align-items: center;
}

/* 数字大字号：戴手套 + 30–80cm 视距下 13px 认不出（UE §1.2） */
.ziwi-qty-field :deep(.van-field__control) {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-2xl);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

/* 单位右置只读：不进输入框（UE §4.2） */
.ziwi-qty-field__unit {
  flex: none;
  min-width: var(--ziwi-touch-min);
  padding: 0 var(--ziwi-gap-sm);
  font-size: var(--ziwi-font-size-lg);
  color: var(--ziwi-text-secondary);
  text-align: right;
  white-space: nowrap;
}

.ziwi-qty-field__step {
  flex: none;
  min-width: var(--ziwi-touch-min);
  min-height: var(--ziwi-touch-min);
}

.ziwi-qty-field__error {
  display: flex;
  align-items: flex-start;
  gap: var(--ziwi-gap-xs);
  margin: var(--ziwi-gap-xs) 0 0;
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-state-danger-fg);
  overflow-wrap: anywhere;
}
</style>
