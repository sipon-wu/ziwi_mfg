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

function onConfirm(params: any) {
  // Vant 4 的 van-picker confirm 回传对象 { selectedValues, selectedOptions, selectedIndexes }
  // selectedValues 为各列选中值的数组，单列选择器取 selectedValues[0] 才是真正的选项 value
  let v: any = null
  if (params && Array.isArray(params.selectedValues) && params.selectedValues.length) {
    v = params.selectedValues[0]
  } else if (params && typeof params === 'object' && 'value' in params) {
    v = (params as any).value
  } else {
    v = params
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
