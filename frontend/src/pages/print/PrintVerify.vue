<script setup lang="ts">
/**
 * 留痕码回查页（二维码扫出来就是这个页面）。
 *
 * ## 这一页要回答的唯一问题
 *
 * 「我手上这张纸，是不是系统出的、现在还作不作数。」
 *
 * 所以判读顺序是刻意的：**先给结论（有效 / 已失效），再给细节**。车间与审核
 * 现场没人愿意在一堆字段里自己推断"所以这纸到底能不能用"。
 *
 * ## 为什么"已失效"必须区分 superseded 与 voided
 *
 * - `superseded`（被新版本取代）：纸上的数**当时是对的**，只是单子后来改过。
 *   该做的是"去要新版"，不是"这纸有问题"。
 * - `voided`（作废/红冲）：这张单的业务**本身被撤销了**，纸上的数不能再引用。
 *
 * 混成一句"已失效"，现场会据此判断错误（把改过单的旧纸当造假，或把作废单当有效）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { verifyArtifact, type PrintVerifyResult } from '@/api/print'
import { errorText } from '@/api/client'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'

const route = useRoute()
const router = useRouter()

const code = String(route.params.code || '')
const result = ref<PrintVerifyResult | null>(null)
const loading = ref(true)
const failed = ref('')

const pageState = computed(() => {
  if (failed.value) return 'failed'
  if (loading.value) return 'loading'
  if (!result.value?.found) return 'empty-true'
  return 'ready'
})

/** 三态判读：有效 / 被新版取代 / 已作废 */
const verdict = computed(() => {
  const r = result.value
  if (!r?.found) return null
  if (r.status === 'voided') {
    return { kind: 'danger', label: '已作废，不可引用', icon: '✕', note: '该单据已被红冲或作废，纸面数据不能再作为依据。' }
  }
  if (r.status === 'superseded') {
    return { kind: 'warning', label: '已被新版本取代', icon: '!', note: '纸面内容在打印当时是正确的，但单据之后被修改过，请索取最新版。' }
  }
  return { kind: 'success', label: '有效', icon: '✓', note: '与系统记录一致，可作为凭证。' }
})

const statusText = computed(() => {
  const m: Record<string, string> = {
    valid: '有效', superseded: '被取代', voided: '已作废',
    draft: '草稿', released: '已下达', in_progress: '生产中', paused: '已暂停',
    completed: '已完工', closed: '已关闭', cancelled: '已取消',
    ACC: '合格', REJ: '不合格', UAI: '待判定',
  }
  const s = result.value?.doc_status || ''
  return m[s] || s || '—'
})

async function load(): Promise<void> {
  loading.value = true
  failed.value = ''
  try {
    result.value = await verifyArtifact(code)
  } catch (e: any) {
    failed.value = errorText(e, '回查失败，请检查网络后重试')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="verify-page">
    <van-nav-bar title="留痕核验" left-arrow @click-left="router.back()" />

    <ZiwiStateView
      v-if="pageState === 'loading'"
      state="loading"
      skeleton="detail"
      object-name="留痕记录"
    />
    <ZiwiStateView
      v-else-if="pageState === 'failed'"
      state="failed"
      :error="{ kind: 'business', message: failed }"
      @retry="load"
    />
    <!-- 空态的默认主操作是「新建」，回查页没有"新建留痕"这回事 → 用空 action 槽消掉 -->
    <ZiwiStateView
      v-else-if="pageState === 'empty-true'"
      state="empty-true"
      object-name="留痕记录"
      hint="该留痕码不存在，或不属于当前租户。请确认这张纸是否由本系统打印。"
    >
      <template #action />
    </ZiwiStateView>

    <div v-else-if="result && verdict" class="verify-page__body">
      <section class="verify-card" :class="`verify-card--${verdict.kind}`">
        <div class="verify-card__badge">
          <span class="verify-card__icon">{{ verdict.icon }}</span>
          <span class="verify-card__label">{{ verdict.label }}</span>
        </div>
        <p class="verify-card__note">{{ verdict.note }}</p>
      </section>

      <van-cell-group title="留痕信息">
        <van-cell title="留痕码" :value="result.verify_code" />
        <van-cell title="单据" :value="`${result.title || ''} ${result.doc_no || ''}`.trim()" />
        <van-cell title="单据状态" :value="statusText" />
        <van-cell title="版本 / 副本" :value="`第 ${result.doc_revision} 版 · 副本 ${result.copy_no}`" />
        <van-cell title="模板" :value="result.template || '—'" />
        <van-cell title="打印人" :value="result.printed_by_name || '—'" />
        <van-cell title="打印时间" :value="result.printed_at || '—'" />
        <van-cell title="页数" :value="String(result.page_count ?? '—')" />
        <van-cell title="内容指纹" :label="result.content_hash">
          <template #value>
            <span class="verify-page__hash">{{ (result.content_hash || '').slice(0, 12) }}…</span>
          </template>
        </van-cell>
      </van-cell-group>

      <p class="verify-page__foot">
        内容指纹是该纸打印时刻完整内容快照的 SHA-256。同一指纹 = 同一份内容；<br />
        指纹不同则说明单据在打印之后被修改过。
      </p>
    </div>
  </div>
</template>

<style scoped>
.verify-page {
  min-height: 100%;
  background: var(--ziwi-bg-light);
  padding-bottom: var(--ziwi-gap-xl);
}

.verify-page__body {
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-md);
}

.verify-card {
  margin: var(--ziwi-gap-md) var(--ziwi-gap-md) 0;
  padding: var(--ziwi-gap-lg);
  border-radius: var(--ziwi-radius-lg);
  border: 1px solid var(--ziwi-state-neutral-bd);
  background: var(--ziwi-state-neutral-bg);
}

/* 三态用双编码：图标 + 文案 + 底色，不靠颜色单独区分（UE §1.2） */
.verify-card--success {
  border-color: var(--ziwi-state-success-bd);
  background: var(--ziwi-state-success-bg);
  color: var(--ziwi-state-success-fg);
}

.verify-card--warning {
  border-color: var(--ziwi-state-warning-bd);
  background: var(--ziwi-state-warning-bg);
  color: var(--ziwi-state-warning-fg);
}

.verify-card--danger {
  border-color: var(--ziwi-state-danger-bd);
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
}

.verify-card__badge {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
}

.verify-card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--ziwi-radius-round);
  border: 2px solid currentColor;
  font-size: var(--ziwi-font-size-lg);
  font-weight: 700;
  line-height: 1;
}

.verify-card__label {
  font-size: var(--ziwi-font-size-2xl);
  font-weight: 700;
}

.verify-card__note {
  margin: var(--ziwi-gap-sm) 0 0;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-regular);
  line-height: var(--ziwi-lineheight-normal);
}

.verify-page__hash {
  font-family: var(--ziwi-font-family);
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-secondary);
}

.verify-page__foot {
  margin: 0 var(--ziwi-gap-md);
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
  line-height: var(--ziwi-lineheight-normal);
}
</style>
