<script setup lang="ts">
/**
 * ZiwiFieldError — 字段就近错误
 *
 * 与 `ZiwiErrorSummary` 成对：摘要回答"有几项要改"，本组件回答"这一项为什么不行"。
 * 两者缺一即违反 UE §5.1「校验失败」行 —— 只给 toast 会被判违规（不定位、3 秒消失）。
 *
 * 硬规则：
 * - 文案格式由 `config/uiText.ts` 的 `txt.validation.*` 生成（`字段 + 问题`），本组件只负责呈现；
 * - `role="alert"` + `aria-live="polite"`：读屏要能听到，但不要打断用户正在输入的内容；
 * - 颜色只取状态令牌（双编码的另一半是左侧图标与文字本身）。
 *
 * 依据：UE §5.1「校验失败」、UE-10。
 */
interface Props {
  /** 错误文案；为空表示无错误（组件不渲染任何 DOM） */
  message?: string | null
  /** 关联的字段 id（供 `aria-describedby` 指向） */
  fieldId?: string
  /** 是否显示左侧图标（默认显示，保证不只靠颜色） */
  showIcon?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  message: null,
  fieldId: '',
  showIcon: true,
})
</script>

<template>
  <p
    v-if="message"
    class="ziwi-field-error"
    role="alert"
    aria-live="polite"
    :id="fieldId || undefined"
  >
    <van-icon v-if="showIcon" name="warning-o" class="ziwi-field-error__icon" />
    <span class="ziwi-field-error__text">{{ message }}</span>
  </p>
</template>

<style scoped>
.ziwi-field-error {
  display: flex;
  align-items: flex-start;
  gap: var(--ziwi-gap-xs);
  margin: var(--ziwi-gap-xs) 0 0;
  padding: 0;
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-state-danger-fg);
  /* R2：长错误文案不能撑开浮层 */
  min-width: 0;
  overflow-wrap: anywhere;
}

.ziwi-field-error__icon {
  flex: none;
  margin-top: 2px;
  font-size: var(--ziwi-font-size-lg);
}

.ziwi-field-error__text {
  flex: 1 1 auto;
  min-width: 0;
}
</style>
