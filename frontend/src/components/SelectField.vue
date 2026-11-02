<script setup lang="ts">
/**
 * SelectField — 兼容薄壳（架构 §2.2「旧名兼容」）
 *
 * 存在的唯一理由：`main.ts` 把 `SelectField` 全局注册了，8 个 basics 页 + 6 个
 * 其他页面用的是全局名。直接改名会让这些页面全部白屏（"Failed to resolve component"）。
 *
 * 因此本文件**只做转发**：
 * - props 集合是旧 SelectField 的超集（`modelValue` / `options` / `placeholder` /
 *   `clearable` / `disabled`），一个字段都不缺；
 * - 行为、DOM、选择交互全部来自 `ZiwiSelect`，本文件不写任何逻辑；
 * - `change` 事件保留旧的**单参数**签名（旧调用方写的是 `@change="v => ..."`）。
 *
 * ★ 闸门：本文件改造后，`pages/basics/` 8 页必须 git diff 为空。
 *   一旦这里"顺手"多做了点事（比如默认值改了、加了校验），闸门就会失败。
 *   因此 `clearable` 的默认值**保持旧行为 `false`**，而 `ZiwiSelect` 自身默认 `true`。
 */
import ZiwiSelect from '@/components/ziwi/ZiwiSelect.vue'
import type { ZiwiOption } from '@/components/ziwi/ZiwiSelectList.vue'

interface Props {
  modelValue?: string | number | null
  /** 选项：`{ label, value }` 或纯字符串数组（旧页两种都出现过） */
  options?: Array<ZiwiOption | string>
  placeholder?: string
  /** 旧默认值为 false —— 薄壳必须保持，否则 8 个 basics 页的筛选框会突然多出清空按钮 */
  clearable?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: null,
  options: () => [],
  placeholder: '',
  clearable: false,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number | null]
  /** 旧签名：只带值（第二参数在旧组件里不存在，这里不透传，避免调用方类型错） */
  change: [value: string | number | null]
}>()

function onUpdate(value: string | number | null): void {
  emit('update:modelValue', value)
}

function onChange(value: string | number | null): void {
  emit('change', value)
}
</script>

<template>
  <ZiwiSelect
    :model-value="props.modelValue"
    :options="props.options"
    :placeholder="props.placeholder"
    :clearable="props.clearable"
    :disabled="props.disabled"
    @update:model-value="onUpdate"
    @change="onChange"
  />
</template>
