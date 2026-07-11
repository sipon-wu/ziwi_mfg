<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: null },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '' },
  clearable: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const showPopup = ref(false)

const columns = computed(() =>
  (props.options || []).map((o: any) => ({ text: o.label, value: o.value })),
)

const currentLabel = computed(() => {
  const found = (props.options || []).find((o: any) => o.value === props.modelValue)
  return found ? found.label : ''
})

const defaultIndex = computed(() => {
  const idx = (props.options || []).findIndex((o: any) => o.value === props.modelValue)
  return idx >= 0 ? idx : 0
})

const hasValue = computed(
  () => props.modelValue !== null && props.modelValue !== undefined && props.modelValue !== '',
)

function open() {
  if (props.disabled) return
  showPopup.value = true
}

function onConfirm(value: any) {
  // van-picker 在对象列下 confirm 的 value 可能是选项的 value 字段，也可能为整个对象，做兼容
  let v = value
  if (value && typeof value === 'object' && 'value' in value) {
    v = value.value
  }
  emit('update:modelValue', v)
  emit('change', v)
  showPopup.value = false
}

function onCancel() {
  showPopup.value = false
}

function onClear() {
  emit('update:modelValue', null)
  emit('change', null)
}
</script>

<template>
  <div class="select-field">
    <van-field
      :model-value="currentLabel"
      :placeholder="placeholder || '请选择'"
      readonly
      :disabled="disabled"
      clickable
      @click="open"
    >
      <template v-if="clearable && hasValue" #button>
        <van-button size="mini" plain type="primary" @click.stop="onClear">清空</van-button>
      </template>
    </van-field>

    <van-popup v-model:show="showPopup" position="bottom" round>
      <van-picker
        :columns="columns"
        :default-index="defaultIndex"
        show-toolbar
        title="请选择"
        @confirm="onConfirm"
        @cancel="onCancel"
      />
    </van-popup>
  </div>
</template>
