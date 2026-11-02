<script lang="ts">
/**
 * 状态种类。放在普通 `<script>` 块里导出（`<script setup>` 不允许 ES 模块导出）。
 */
export type StateKind =
  | 'loading'
  | 'empty-true'
  | 'empty-filtered'
  | 'empty-scoped'
  | 'failed'
  | 'forbidden'
  | 'offline'
  | 'ready'
</script>

<script setup lang="ts">
/**
 * ZiwiStateView — 状态统一视图（UE §5.1 七状态中由组件承载的那几类）
 *
 * ## 分工（谁承载哪一种状态）
 * | 状态 | 载体 |
 * |---|---|
 * | 加载中 / 空四类 / 失败 / 无权限 / 离线 | **本组件** |
 * | 校验失败 | `ZiwiErrorSummary` + `ZiwiFieldError` |
 * | 保存成功 | `ZiwiReceipt` |
 * | 危险操作 | `ZiwiConfirmSheet` |
 *
 * ## 硬规则
 * 1. 页面**禁止**再直写 `van-empty description="暂无数据"`（四类空态混成一句 = UE-12 违规）；
 * 2. `failed` 与 `offline` 的文案与动作必须不同（一个是"重试"，一个是"看队列"）；
 * 3. 加载态用骨架并**保持最终布局尺寸**，不允许居中转圈把内容挤走；
 * 4. `forbidden` 必须给出可复制的权限码（UE-14，用户要能发给管理员）。
 *
 * 依据：UE §5.1、§5.3、UE-09/12/14；架构 §2.4。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { txt } from '@/config/uiText'

/** 状态种类 */

interface Props {
  state: StateKind
  /** 骨架形态 */
  skeleton?: 'rows' | 'cards' | 'detail'
  /** 骨架条数（列表首屏 3 行） */
  skeletonCount?: number
  /** 403 所需权限码（forbidden 必填） */
  permCode?: string
  /** 当前生效的筛选条件（empty-filtered 回显） */
  conditions?: string[]
  /** 待提交条数（offline） */
  pendingCount?: number
  /** 失败信息，网络失败与业务失败文案必须不同 */
  error?: { kind: 'network' | 'business'; message?: string }
  /** 空态主操作文案 */
  primaryText?: string
  /** 最小高度，用于稳定布局不跳动 */
  minHeight?: string
  /** 空态/失败态的说明对象名，如「保养计划」 */
  objectName?: string
  /** 无数据范围时的范围描述，如「本班组」「本部门」 */
  scopeLabel?: string
}

const props = withDefaults(defineProps<Props>(), {
  skeleton: 'rows',
  skeletonCount: 3,
  permCode: '',
  conditions: () => [],
  pendingCount: 0,
  error: undefined,
  primaryText: '',
  minHeight: '',
  objectName: '数据',
  scopeLabel: '本班组',
})

const emit = defineEmits<{
  retry: []
  'clear-filter': []
  create: []
  'copy-perm': []
  back: []
  'view-queue': []
}>()

/* ------------------------------------------------------------------ *
 * 文案（全部取自 uiText，组件不拼字符串）
 * ------------------------------------------------------------------ */

const isReady = computed(() => props.state === 'ready')
const isLoading = computed(() => props.state === 'loading')

const skeletonRows = computed(() => Math.max(1, props.skeletonCount))

const iconName = computed(() => {
  switch (props.state) {
    case 'empty-true':
      return 'records-o'
    case 'empty-filtered':
      return 'search'
    case 'empty-scoped':
      return 'lock'
    case 'failed':
      return 'warning-o'
    case 'forbidden':
      return 'shield-o'
    case 'offline':
      return 'wifi-o'
    default:
      return 'info-o'
  }
})

/** 主文案 */
const titleText = computed(() => {
  switch (props.state) {
    case 'empty-true':
      return txt.empty.true(props.objectName, txt.action.create)
    case 'empty-filtered':
      return txt.empty.filtered(props.conditions.join('、') || '数据')
    case 'empty-scoped':
      return txt.empty.scoped(props.scopeLabel)
    case 'failed':
      return props.error?.kind === 'network'
        ? txt.error.network()
        : props.error?.message
          ? txt.error.business(props.error.message)
          : txt.empty.failed()
    case 'forbidden':
      return txt.error.forbidden(props.permCode || '未知权限码')
    case 'offline':
      return txt.offline.bar(props.pendingCount)
    default:
      return ''
  }
})

/** 副文案（"下一步怎么做"） */
const hintText = computed(() => {
  switch (props.state) {
    case 'empty-filtered':
      return '可以换条件，或清空条件看全部'
    case 'empty-scoped':
      return txt.empty.scopedHint()
    case 'failed':
      return props.error?.kind === 'network' ? txt.error.networkAction() : txt.error.server()
    case 'forbidden':
      return txt.error.forbiddenHint()
    case 'offline':
      return txt.offline.queued(props.pendingCount)
    case 'empty-true':
      return '点右下角新建，或在扫码入口直接扫设备码'
    default:
      return ''
  }
})

/** 主操作文案 */
const primaryLabel = computed(() => {
  if (props.primaryText) return props.primaryText
  switch (props.state) {
    case 'empty-true':
      return `${txt.action.create}第一个${props.objectName}`
    case 'empty-filtered':
      return txt.empty.filteredAction()
    case 'failed':
      return txt.empty.failedAction()
    case 'offline':
      return txt.action.retry
    default:
      return ''
  }
})

/** 主操作是否可点（forbidden 没有可执行动作，只有"复制权限码"与"返回"） */
const hasPrimary = computed(() =>
  ['empty-true', 'empty-filtered', 'failed', 'offline'].includes(props.state),
)

function onPrimary(): void {
  switch (props.state) {
    case 'empty-true':
      emit('create')
      return
    case 'empty-filtered':
      emit('clear-filter')
      return
    case 'failed':
      emit('retry')
      return
    case 'offline':
      emit('view-queue')
      return
    default:
      return
  }
}

/* ------------------------------------------------------------------ *
 * 权限码复制（http 环境 navigator.clipboard 可能不存在 → 降级为选中文本）
 * ------------------------------------------------------------------ */

const copied = ref(false)
const copyFallback = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function onCopyPerm(): Promise<void> {
  const code = props.permCode
  if (!code) return
  emit('copy-perm')
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(code)
      copied.value = true
      copyFallback.value = false
    } else {
      copyFallback.value = true
    }
  } catch {
    copyFallback.value = true
  }
  if (copiedTimer !== null) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copied.value = false
    copiedTimer = null
  }, 2000)
}

const rootStyle = computed(() =>
  props.minHeight ? { minHeight: props.minHeight } : undefined,
)

onBeforeUnmount(() => {
  if (copiedTimer !== null) {
    clearTimeout(copiedTimer)
    copiedTimer = null
  }
})
</script>

<template>
  <div
    v-if="!isReady"
    class="ziwi-state-view"
    :class="`ziwi-state-view--${state}`"
    :style="rootStyle"
  >
    <!-- ① 加载中：骨架，保持最终布局尺寸（不出现居中转圈把内容挤走） -->
    <div v-if="isLoading" class="ziwi-state-view__skeleton" aria-busy="true" aria-live="polite">
      <slot name="skeleton">
        <div
          v-for="i in skeletonRows"
          :key="i"
          class="ziwi-state-view__sk-item"
          :class="`ziwi-state-view__sk-item--${skeleton}`"
        >
          <span class="ziwi-state-view__sk-bar ziwi-state-view__sk-bar--main" />
          <span class="ziwi-state-view__sk-bar ziwi-state-view__sk-bar--sub" />
        </div>
      </slot>
      <span class="ziwi-state-view__sr">加载中</span>
    </div>

    <!-- ② 其余六态：图标 + 文案 + 动作 -->
    <div v-else class="ziwi-state-view__inner">
      <van-icon :name="iconName" class="ziwi-state-view__icon" />
      <p class="ziwi-state-view__title">{{ titleText }}</p>
      <p v-if="hintText" class="ziwi-state-view__hint">{{ hintText }}</p>

      <!-- 筛选条件回显：用户要能看到"我是被什么条件挡住的" -->
      <div v-if="state === 'empty-filtered' && conditions.length" class="ziwi-state-view__tags">
        <van-tag
          v-for="cond in conditions"
          :key="cond"
          type="primary"
          size="medium"
          plain
        >
          {{ cond }}
        </van-tag>
      </div>

      <!-- 权限码：可复制（UE-14） -->
      <div v-if="state === 'forbidden'" class="ziwi-state-view__perm">
        <code class="ziwi-state-view__perm-code">{{ permCode || '未知权限码' }}</code>
        <van-button size="small" plain type="primary" @click="onCopyPerm">
          {{ copied ? '已复制' : '复制权限码' }}
        </van-button>
      </div>
      <input
        v-if="copyFallback"
        class="ziwi-state-view__perm-input"
        :value="permCode"
        readonly
        @focus="($event.target as HTMLInputElement).select()"
      />

      <div class="ziwi-state-view__actions">
        <slot name="action">
          <van-button
            v-if="hasPrimary"
            type="primary"
            class="ziwi-state-view__btn"
            @click="onPrimary"
          >
            {{ primaryLabel }}
          </van-button>
          <van-button
            v-if="state === 'forbidden'"
            plain
            class="ziwi-state-view__btn"
            @click="emit('back')"
          >
            {{ txt.action.back }}
          </van-button>
        </slot>
      </div>
    </div>
  </div>

  <!-- ③ ready：透传默认插槽 -->
  <slot v-else />
</template>

<style scoped>
.ziwi-state-view {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: var(--ziwi-gap-2xl) var(--ziwi-gap-lg);
  background: var(--ziwi-bg-white);
}

.ziwi-state-view__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  width: 100%;
  max-width: 480px;
  min-width: 0;
  text-align: center;
}

.ziwi-state-view__icon {
  font-size: 40px;
  color: var(--ziwi-text-muted);
}

.ziwi-state-view--failed .ziwi-state-view__icon,
.ziwi-state-view--forbidden .ziwi-state-view__icon {
  color: var(--ziwi-state-danger-fg);
}

.ziwi-state-view--offline .ziwi-state-view__icon {
  color: var(--ziwi-state-warning-fg);
}

.ziwi-state-view__title {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 500;
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-primary);
  overflow-wrap: anywhere;
}

.ziwi-state-view__hint {
  margin: 0;
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-secondary);
  overflow-wrap: anywhere;
}

.ziwi-state-view__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ziwi-gap-sm);
  justify-content: center;
}

.ziwi-state-view__perm {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  flex-wrap: wrap;
  justify-content: center;
  margin-top: var(--ziwi-gap-sm);
}

.ziwi-state-view__perm-code {
  padding: var(--ziwi-gap-xs) var(--ziwi-gap-sm);
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-bg-light);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-primary);
  /* 长权限码必须能换行，不能撑破 412 视口（R2 / UE-04） */
  overflow-wrap: anywhere;
}

.ziwi-state-view__perm-input {
  width: 100%;
  margin-top: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm);
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  font-size: var(--ziwi-font-size-md);
}

.ziwi-state-view__actions {
  display: flex;
  align-items: center;
  gap: var(--ziwi-touch-gap-sem);
  margin-top: var(--ziwi-gap-md);
}

.ziwi-state-view__btn {
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

/* ── 骨架 ── */
.ziwi-state-view__skeleton {
  width: 100%;
  max-width: 720px;
  min-width: 0;
}

.ziwi-state-view__sk-item {
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-sm);
  /* 骨架条高度 = 行高令牌，保证加载完成后布局不跳动 */
  min-height: var(--ziwi-row-min-h);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  box-sizing: border-box;
  border-bottom: 1px solid var(--ziwi-border-light);
}

.ziwi-state-view__sk-item--cards {
  border: 1px solid var(--ziwi-border-light);
  border-radius: var(--ziwi-radius-lg);
  margin-bottom: var(--ziwi-gap-sm);
}

.ziwi-state-view__sk-item--detail {
  min-height: calc(var(--ziwi-row-min-h) * 2);
}

.ziwi-state-view__sk-bar {
  display: block;
  height: 12px;
  border-radius: var(--ziwi-radius-sm);
  background: linear-gradient(
    90deg,
    var(--ziwi-border-light) 25%,
    var(--ziwi-border) 37%,
    var(--ziwi-border-light) 63%
  );
  background-size: 400% 100%;
  animation: ziwi-skeleton 1.2s ease infinite;
}

.ziwi-state-view__sk-bar--main {
  width: 60%;
}

.ziwi-state-view__sk-bar--sub {
  width: 35%;
  height: 10px;
}

@keyframes ziwi-skeleton {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

/* 减少动效偏好下不闪（UE-20：信息不丢，只是不闪） */
@media (prefers-reduced-motion: reduce) {
  .ziwi-state-view__sk-bar {
    animation: none;
  }
}

/* 读屏可见、视觉隐藏 */
.ziwi-state-view__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
