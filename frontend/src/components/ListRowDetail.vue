<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import type { FieldDef } from '@/types/search'

/**
 * ListRowDetail —— 「并集方式」行展开详情
 *
 * 设计范式（对齐 知微智能制造.xmind 信息架构）：
 *  - 列表 = 多列表格；详情 = 该实体「全部字段并集」平铺展示。
 *  - 字段并集 = 列表字段 ∪ 详情独有字段 ∪ 审计字段(remark/created_at/关联 id)
 *            = props.fields 全量（不再按 hidden 去重）。
 *  - 布局 = Odoo 风格「多列并排」：每字段一列，label 小字在上、value 在下，
 *           超宽时外层横向滚动、不折叠（无展开/收起按钮）。
 *  - 移动端（≤768px）grid 退化为单列，保证可读。
 */

const props = defineProps<{
  item: Record<string, any>
  fields: FieldDef[]
}>()

/** 并集字段：直接全量渲染 props.fields（含 hidden:true 的审计/关联字段），不再过滤 */
const unionFields = computed<FieldDef[]>(() => props.fields)

/** 并集字段总数 */
const totalCount = computed(() => props.fields.length)

/** 主键摘要：优先取 name/code，否则取第一个字段值；用于 header 上下文 */
const primarySummary = computed<string>(() => {
  const nameVal = props.item?.name
  if (nameVal != null && String(nameVal).trim()) return String(nameVal)
  const codeVal = props.item?.code
  if (codeVal != null && String(codeVal).trim()) return String(codeVal)
  const first = props.fields[0]
  if (first) return display(first)
  return '—'
})

/** 视口宽度判定：≤768px 视为窄屏（移动端），grid 退化为单列 */
const isNarrow = ref(false)
function updateViewport(): void {
  isNarrow.value = window.matchMedia('(max-width: 768px)').matches
}
onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
})

/**
 * 列式 grid 模板：
 *  - 窄屏：单列 1fr（垂直堆叠，保证可读）。
 *  - 宽屏：按字段数生成固定列宽的 grid（每列 minmax(150px,240px)）。
 *          当 列数 × 150px 超过容器宽度时，外层容器出现横向滚动条（不折叠）。
 */
const gridStyle = computed<Record<string, string>>(() => {
  if (isNarrow.value) {
    return { gridTemplateColumns: '1fr' }
  }
  const count = props.fields.length
  return { gridTemplateColumns: `repeat(${count}, minmax(150px, 240px))` }
})

/**
 * 统一的字段值格式化（保留 v2 逻辑）：
 *  - boolean -> 是/否
 *  - enum -> 选项 label
 *  - date -> 截取 YYYY-MM-DD
 *  - object -> JSON.stringify
 *  - 空(null/undefined/空串) -> '--'
 */
function display(f: FieldDef): string {
  const v = props.item?.[f.key]
  if (v === null || v === undefined || v === '') return '--'
  if (f.type === 'boolean') return v === true || v === 'true' || v === 1 || v === '1' ? '是' : '否'
  if (f.type === 'enum' && f.options) {
    const opt = f.options.find((o) => String(o.value) === String(v))
    return opt ? opt.label : String(v)
  }
  if (f.type === 'date') {
    const s = String(v)
    return s.length >= 10 ? s.slice(0, 10) : s
  }
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v)
    } catch {
      return String(v)
    }
  }
  return String(v)
}
</script>

<template>
  <div class="row-detail">
    <div class="rd-header" v-if="primarySummary">
      <span class="rd-header-summary">{{ primarySummary }}</span>
      <span class="rd-header-count">{{ totalCount }} 字段</span>
    </div>

    <!-- 外层可横向滚动容器：超宽时横向滚动、不折叠 -->
    <div class="rd-scroll">
      <!-- 内层多列并排 grid：每列 = 一字段单元（label 在上，value 在下） -->
      <div class="rd-grid" :style="gridStyle">
        <div v-for="f in unionFields" :key="f.key" class="rd-cell">
          <span class="rd-label">{{ f.label }}</span>
          <span class="rd-value" :class="{ 'rd-empty': display(f) === '--' }">
            {{ display(f) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row-detail {
  /* 不硬编码浅色背景：透明继承父级（列表行）底色，深色/浅色环境均自适配 */
  padding: 12px 16px 14px;
  background: transparent;
  /* Odoo 嵌入式详情观感：左侧主色条 + 顶部虚线分隔，与列表列风格一致 */
  border-left: 3px solid var(--ziwi-primary, #0d7377);
  border-top: 1px dashed var(--ziwi-border, #ebedf0);
  /* 修复横向滚动失效：组件位于 van-cell 的 flex 链内，van-cell__label 作为
     flex 项默认 min-width:auto = 其 min-content（多列并集网格宽），
     导致它不被压缩、把 .rd-scroll 撑到内容全宽，overflow-x:auto 永不触发、
     最右列被祖先 overflow:hidden 裁剪。
     此处 overflow:hidden 使 .row-detail 自身成为滚动容器，其 min-content 归零，
     从而阻断 min-content 向上传播，van-cell__label 可被压缩到单元格宽度内，
     内层 .rd-scroll 才能产生真正的内部横向滚动条（末列可达）。 */
  min-width: 0;
  overflow: hidden;
}

/* ---------- header ---------- */
.rd-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 0.5px solid var(--ziwi-border, #ebedf0);
  font-size: 13px;
}
.rd-header-summary {
  font-weight: 500;
  color: var(--ziwi-text-primary, #1e293b);
}
.rd-header-count {
  font-size: 12px;
  color: var(--ziwi-text-muted, #999999);
}

/* ---------- 横向滚动容器 ---------- */
.rd-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 2px;
  /* 约束在单元格（父级 .row-detail / van-cell__label）宽度内，
     配合 flex 链 min-width:0，使超宽网格产生内部横向滚动而非撑破布局 */
  width: 100%;
  max-width: 100%;
  min-width: 0;
}
/* 细滚动条，避免遮挡内容 */
.rd-scroll::-webkit-scrollbar {
  height: 6px;
}
.rd-scroll::-webkit-scrollbar-thumb {
  background: var(--ziwi-border, #e2e8f0);
  border-radius: 3px;
}

/* ---------- 多列并排 grid ---------- */
.rd-grid {
  display: grid;
  gap: 10px 16px;
  /* grid-template-columns 由 gridStyle 动态注入（宽屏多列/窄屏单列） */
}

.rd-cell {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 2px 0;
}

.rd-label {
  color: var(--ziwi-text-muted, #999999);
  font-size: 12px;
  line-height: 1.4;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rd-value {
  color: var(--ziwi-text-primary, #1e293b);
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
  overflow-wrap: anywhere;
  min-width: 0;
}

/* 空值态 */
.rd-empty {
  color: var(--ziwi-text-muted, #c0c4cc);
}

/* ---------- 移动端单列（兜底，由 gridStyle 已处理，作为样式双保险） ---------- */
@media (max-width: 768px) {
  .rd-grid {
    grid-template-columns: 1fr !important;
  }
  .rd-label {
    white-space: normal;
  }
}
</style>

<!-- 全局（非 scoped）：修复 van-cell flex 链撑宽导致 .rd-scroll 横滚失效。
     van-cell 为 display:flex 容器，其标题/值/描述槽（__title/__value/__label）
     作为 flex 项默认 min-width:auto，会被多列并集内容撑破单元格宽度。
     统一置 min-width:0 使其可收缩，配合 .row-detail 的 overflow:hidden，
     使内部 .rd-scroll 的横向滚动条生效、最右列可达。
     该规则仅放开 flex 项最小宽度，不影响普通单元格的正常排版，风险极低。 -->
<style>
.van-cell__title,
.van-cell__value,
.van-cell__label {
  min-width: 0;
}
</style>
