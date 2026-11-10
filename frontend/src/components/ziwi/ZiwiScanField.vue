<script setup lang="ts">
/**
 * ZiwiScanField — 扫码输入位（三通道：物理扫描键 / 软扫 / 手输）
 *
 * ## 为什么车间必须默认扫码
 * 手输 14 位设备编码在手套 + 油污下的错误率极高（UE §2.5「扫码优先于选择」）。
 * 扫码枪本质是键盘，会在极短时间"逐字符键入 + Enter"，因此聚合判定条件是
 * **连续字符 + Enter**（实现见 `composables/useScanInput.ts`）。
 *
 * ## 三通道
 * 1. **物理扫描键**：输入框获得焦点即可，回车成码；
 * 2. **软扫**：页面调 `emit('scan')` 之外，也可由父级直接调 `componentRef.flush(text)`；
 * 3. **手输兜底**：手输后按回车同样成码（不允许"只能扫码"死路，UE §5.1 失败态）。
 *
 * 硬规则：焦点必须在输入框内才能收硬键；因此提供"点整行聚焦"与大热区扫码按钮（UE-P0-02）。
 *
 * 依据：UE §2.5、§6.1、UE-15；架构 §5.2。
 */
import { computed, ref } from 'vue'
import { SCAN_MIN_LENGTH, useScanInput } from '@/composables/useScanInput'
import { txt } from '@/config/uiText'

interface Props {
  /** 当前值（手输/扫码后同步给页面） */
  modelValue?: string
  label?: string
  placeholder?: string
  disabled?: boolean
  /** 扫码对象名，用于提示文案，如「设备码」 */
  objectName?: string
  /** 是否自动聚焦（进入页面即待扫，少一次点击） */
  autofocus?: boolean
  /** 字段名，渲染成 data-field 供表单定位 */
  fieldName?: string
  /** 扫码后是否自动清空输入框（连续扫描场景，默认 true） */
  clearOnScan?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  label: '',
  placeholder: '扫码或输入编码后回车',
  disabled: false,
  objectName: '编码',
  autofocus: false,
  fieldName: '',
  clearOnScan: true,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  /** 收到一次完整码（硬键 / 粘贴 / 回车手输 三通道归一） */
  scan: [code: string]
  /** 输入内容变化（未成码） */
  typing: [value: string]
}>()

const innerValue = ref(props.modelValue ?? '')

const { isScanning, handleKeydown, handlePaste } = useScanInput({
  onScan: (code: string) => {
    emit('scan', code)
    if (props.clearOnScan) {
      innerValue.value = ''
      emit('update:modelValue', '')
    } else {
      innerValue.value = code
      emit('update:modelValue', code)
    }
    return true
  },
  // ★ 不在这里传 minLength：用 composable 的 SCAN_MIN_LENGTH（单一真源）。
  //   此前这里写死 3、composable 默认 4，两处并存，改一处另一处不变。
})

/** 扫码提示：识别中给出明确反馈（A2：操作已生效） */
const hintText = computed(() =>
  isScanning.value ? `正在识别${props.objectName}…` : `对准${props.objectName}扫一下，或手输后回车`,
)

function onInput(value: string): void {
  innerValue.value = value ?? ''
  emit('update:modelValue', innerValue.value)
  emit('typing', innerValue.value)
}

function onKeydown(event: KeyboardEvent): void {
  // ★ 把输入框当前值一起交过去：回车以"框里现在是什么"为准。
  //   不传的话就是老行为 —— 慢速手输时内部缓冲被重置成最后一个字符，
  //   回车判定"太短"，然后静默清空，界面上什么都不发生（2026-11-10 实测）。
  handleKeydown(event, innerValue.value)
}

/** 手输兜底：值够长时把当前值当成一次扫码结果 */
function onConfirm(): void {
  const code = innerValue.value.trim()
  if (code.length < SCAN_MIN_LENGTH) {
    emit('scan', '')
    return
  }
  emit('scan', code)
  if (props.clearOnScan) {
    innerValue.value = ''
    emit('update:modelValue', '')
  }
}

/** 供页面软扫调用（相机/系统扫码头把结果塞进来） */
function feed(code: string): void {
  const value = (code ?? '').trim()
  if (!value) return
  onConfirmWith(value)
}

function onConfirmWith(value: string): void {
  emit('scan', value)
  if (props.clearOnScan) {
    innerValue.value = ''
    emit('update:modelValue', '')
  } else {
    innerValue.value = value
    emit('update:modelValue', value)
  }
}

defineExpose({ feed, onConfirm })
</script>

<template>
  <div class="ziwi-scan-field" :data-field="fieldName || undefined">
    <van-field
      class="ziwi-scan-field__field"
      :model-value="innerValue"
      :label="label"
      :placeholder="placeholder"
      :disabled="disabled"
      :autofocus="autofocus"
      type="text"
      inputmode="text"
      autocomplete="off"
      @update:model-value="onInput"
      @keydown="onKeydown"
      @paste="handlePaste"
    >
      <template #button>
        <van-button
          class="ziwi-scan-field__btn"
          size="small"
          type="primary"
          plain
          :disabled="disabled"
          icon="scan"
          @click="onConfirm"
        >
          {{ txt.action.scan }}
        </van-button>
      </template>
    </van-field>
    <p class="ziwi-scan-field__hint" aria-live="polite">{{ hintText }}</p>
  </div>
</template>

<style scoped>
.ziwi-scan-field {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.ziwi-scan-field :deep(.van-field__body) {
  min-height: var(--ziwi-touch-min);
  align-items: center;
}

/* 输入区本身是热区：点整行即聚焦，避免"点不到输入框"（UE-P0-02） */
.ziwi-scan-field :deep(.van-field__control) {
  min-height: var(--ziwi-touch-min);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: 0.02em;
}

.ziwi-scan-field__btn {
  /* 扫码按钮是高频操作，热区必须达标（不走 mini 档） */
  min-height: var(--ziwi-touch-min);
  padding: 0 var(--ziwi-gap-md);
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-scan-field__hint {
  margin: var(--ziwi-gap-xs) 0 0;
  font-size: var(--ziwi-font-size-sm);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-muted);
}
</style>
