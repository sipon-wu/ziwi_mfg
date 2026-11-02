<script setup lang="ts">
/**
 * ZiwiPrintButton — 单据打印入口。
 *
 * 只做一件事：带 type/id 跳到打印预览页。**不在这里发请求**，因为
 * 每发一次就是一份留痕（副本号 +1）——用户可能只是想看一眼就返回，
 * 一进详情页就悄悄打了一份，账就对不上了。
 *
 * 热区与按钮档位由 `--ziwi-touch-min` / 令牌保证，符合 R4（主操作拇指可达）。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'

interface Props {
  docType: string
  docId: string | number
  text?: string
  /** 撑满一行（宽屏下默认只占内容宽） */
  block?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  text: '打印',
  block: false,
  disabled: false,
})

const router = useRouter()

const canJump = computed(
  () => !props.disabled && props.docType !== '' && String(props.docId) !== '',
)

function go(): void {
  if (!canJump.value) return
  router.push({
    name: 'PrintPreview',
    params: { docType: props.docType, docId: String(props.docId) },
  })
}
</script>

<template>
  <van-button
    class="ziwi-print-btn"
    :class="{ 'ziwi-print-btn--block': block }"
    plain
    :disabled="!canJump"
    @click="go"
  >
    {{ text }}
  </van-button>
</template>

<style scoped>
.ziwi-print-btn {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-print-btn--block {
  width: 100%;
}
</style>
