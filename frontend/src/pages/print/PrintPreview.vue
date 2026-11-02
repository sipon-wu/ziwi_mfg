<script setup lang="ts">
/**
 * 打印预览页（全屏，不带侧边栏 / 顶栏）。
 *
 * ## 为什么单独一页，而不是详情页里弹个框
 *
 * 打印是"眼睛盯着纸"的动作，界面必须让位：宽屏一体机上要能看到整页 A4，
 * 手持终端上不能有侧边栏挤压。所以这一页**不进 MainLayout**。
 *
 * ## 为什么要显示留痕码
 *
 * 打印员在车间必须能当场核对"手里这张纸和屏幕上是不是同一份"——留痕码
 * 印在纸上、显示在屏幕上，对得上才是同一份。没有这一步，纸掉了、打重了
 * 都发现不了。
 *
 * ## 关于「点了打印没反应」
 *
 * Chrome 的 PDF 插件不接受父窗口的 `print()`。所以按钮先试一次，试不动就
 * 明确提示「用预览右上角的打印图标」——比静默无反应强。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import {
  PAPER_LABEL,
  renderPrint,
  triggerPrint,
  type PrintArtifactMeta,
  type PrintPaper,
} from '@/api/print'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'

const route = useRoute()
const router = useRouter()

const docType = String(route.params.docType || '')
const docId = String(route.params.docId || '')

/** 纸型从 query 来（详情页「打印流转卡」/「打印贴标」分别带 a4 / label80）。 */
const paper = computed<PrintPaper>(() =>
  String(route.query.paper || '') === 'label80' ? 'label80' : 'a4',
)

/** 单据类型 → 中文名。新增可打印单据时这里也要加一行（否则页面标题是英文码）。 */
const DOC_TITLE: Record<string, string> = {
  work_order: '生产工单流转卡',
  inspection_order: '检验记录单',
}

const url = ref('')
const meta = ref<PrintArtifactMeta | null>(null)
const loading = ref(true)
const failed = ref('')
const frame = ref<HTMLIFrameElement | null>(null)
const hint = ref('')

/** 页面上不需要滚动的场景，iframe 高度撑满剩余空间 */
const pageState = computed(() => {
  if (failed.value) return 'failed'
  if (loading.value) return 'loading'
  return 'ready'
})

/** 常驻提示。标签纸的缩放警告要在点之前就看得见 —— 用户完全可能直接用
 *  PDF 查看器自带的打印按钮，绕过我们那个 toast。 */
const footerTip = computed(() => {
  if (hint.value) return hint.value
  return paper.value === 'label80'
    ? '热敏标签：打印请选「实际大小 / 100%」，缩放会让二维码扫不出来'
    : ''
})

async function load(): Promise<void> {
  loading.value = true
  failed.value = ''
  try {
    const r = await renderPrint(docType, docId, paper.value)
    url.value = r.url
    meta.value = r.meta
  } catch (e: any) {
    failed.value = e?.readable || e?.message || '打印失败'
  } finally {
    loading.value = false
  }
}

function onPrint(): void {
  const ok = triggerPrint(frame.value)
  // 标签必须提醒缩放：二维码模块是 0.5mm（203dpi 下正好 4 dots）算死的，
  // 打印对话框只要勾了「适合纸张」就会缩放，模块变成 3 dots 或糊成 5 dots，
  // 手持机当场扫不出来 —— 而纸已经贴到工件上了，只能撕掉重打。
  hint.value = paper.value === 'label80'
    ? (ok
      ? '打印对话框请选「实际大小 / 100%」，不要勾「适合纸张」；无窗口弹出时点 PDF 右上角打印图标'
      : '请在 PDF 右上角打印图标里选「实际大小 / 100%」打印')
    : (ok
      ? '若无打印窗口弹出，请点 PDF 预览右上角的打印图标'
      : '请点 PDF 预览右上角的打印图标完成打印')
  showToast({ message: hint.value, position: 'bottom' })
}

function onDownload(): void {
  if (!url.value) return
  const a = document.createElement('a')
  a.href = url.value
  const suffix = paper.value === 'a4' ? '' : '-label'
  a.download = `${meta.value?.docNo || docType}-V${meta.value?.revision || 1}C${meta.value?.copyNo || 1}${suffix}.pdf`
  a.click()
}

onMounted(load)

onBeforeUnmount(() => {
  // 不 revoke 会让整个 PDF 一直驻留内存；车间一体机常年不关浏览器
  if (url.value) URL.revokeObjectURL(url.value)
})
</script>

<template>
  <div class="print-page">
    <header class="print-page__bar">
      <button type="button" class="print-page__back" aria-label="返回" @click="router.back()">
        ←
      </button>
      <div class="print-page__titles">
        <div class="print-page__title">
          {{ DOC_TITLE[docType] || docType }}
          <span class="print-page__paper">{{ PAPER_LABEL[paper] }}</span>
        </div>
        <div v-if="meta" class="print-page__sub">
          留痕码 {{ meta.verifyCode }} · 第 {{ meta.revision }} 版 · 副本 {{ meta.copyNo }}
        </div>
      </div>
    </header>

    <main class="print-page__body">
      <ZiwiStateView
        v-if="pageState !== 'ready'"
        :state="pageState"
        skeleton="detail"
        object-name="打印文件"
        :error="failed ? { kind: 'business', message: failed } : undefined"
        primary-text="重新生成"
        @retry="load"
      />
      <iframe v-else ref="frame" class="print-page__frame" :src="url" title="打印预览" />
    </main>

    <footer v-if="pageState === 'ready'" class="print-page__foot">
      <div v-if="footerTip" class="print-page__hint">{{ footerTip }}</div>
      <div class="print-page__actions">
        <van-button class="print-page__btn" plain @click="onDownload">下载 PDF</van-button>
        <van-button class="print-page__btn" type="primary" @click="onPrint">打印</van-button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.print-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  /* dvh 修正手持机浏览器地址栏收起时的高度跳变 */
  height: 100dvh;
  background: var(--ziwi-bg-light);
}

.print-page__bar {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  padding-top: calc(var(--ziwi-gap-sm) + env(safe-area-inset-top, 0px));
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
}

/* 返回键必须是裸手 48 以上的热区，不能做成 24px 小图标 */
.print-page__back {
  flex: 0 0 auto;
  width: var(--ziwi-touch-min);
  height: var(--ziwi-touch-min);
  border: none;
  border-radius: var(--ziwi-radius-md);
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-primary);
  font-size: var(--ziwi-font-size-xl);
  line-height: 1;
  cursor: pointer;
}

.print-page__back:active {
  transform: scale(var(--ziwi-motion-tap-scale));
  transition: transform var(--ziwi-motion-tap-duration) var(--ziwi-motion-tap-easing);
}

.print-page__titles {
  min-width: 0;
}

.print-page__title {
  font-size: var(--ziwi-font-size-lg);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}

/* 纸型徽标：两种纸的版面差别很大，标题上必须一眼能看出打开的是哪一种 */
.print-page__paper {
  display: inline-block;
  margin-left: var(--ziwi-gap-xs);
  padding: 1px 6px;
  border-radius: var(--ziwi-radius-sm);
  background: var(--ziwi-bg-light);
  color: var(--ziwi-text-muted);
  font-size: var(--ziwi-font-size-xs);
  font-weight: 400;
  vertical-align: middle;
}

.print-page__sub {
  margin-top: 2px;
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
}

.print-page__body {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--ziwi-gap-sm);
}

.print-page__frame {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: var(--ziwi-radius-md);
  background: var(--ziwi-bg-white);
}

.print-page__foot {
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  padding-bottom: calc(var(--ziwi-gap-sm) + env(safe-area-inset-bottom, 0px));
  background: var(--ziwi-bg-white);
  border-top: 1px solid var(--ziwi-border);
}

.print-page__hint {
  margin-bottom: var(--ziwi-gap-xs);
  font-size: var(--ziwi-font-size-xs);
  color: var(--ziwi-text-muted);
}

.print-page__actions {
  display: flex;
  gap: var(--ziwi-touch-gap-sem);
}

.print-page__btn {
  flex: 1 1 0;
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

/* 宽屏：打印预览要看到整页，操作区收窄靠右，不占满一整条 */
@media (min-width: 1024px) {
  .print-page__foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ziwi-gap-lg);
  }

  .print-page__hint {
    margin-bottom: 0;
  }

  .print-page__actions {
    flex: 0 0 auto;
  }

  .print-page__btn {
    flex: 0 0 auto;
    min-width: 140px;
  }
}
</style>
