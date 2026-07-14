<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { FieldDef } from '@/types/search'

const props = defineProps<{
  item: Record<string, any>
  fields: FieldDef[]
}>()

/** 长文本折叠状态（key → 是否已展开） */
const expanded = reactive<Record<string, boolean>>({})

/** 主键摘要：优先取 name/code，否则取第一个非 hidden 字段值 */
const primarySummary = computed(() => {
  const nameVal = props.item?.name
  if (nameVal && String(nameVal).trim()) return String(nameVal)
  const codeVal = props.item?.code
  if (codeVal && String(codeVal).trim()) return String(codeVal)
  const first = props.fields[0]
  if (first) return display(first)
  return '—'
})

function display(f: FieldDef): string {
  const v = props.item[f.key]
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

function isLongValue(f: FieldDef): boolean {
  return display(f).length > 30
}

function toggleExpand(key: string) {
  expanded[key] = true
}
</script>

<template>
  <div class="row-detail">
    <div class="rd-header">
      <span class="rd-header-summary">{{ primarySummary }}</span>
      <span class="rd-header-count">{{ fields.length }} 字段</span>
    </div>
    <div class="rd-grid-wrapper">
      <div class="rd-grid">
        <div v-for="f in fields" :key="f.key" class="rd-col">
          <div class="rd-label">{{ f.label }}</div>
          <div
            class="rd-value"
            :class="{ 'rd-empty': display(f) === '--' }"
            @click="isLongValue(f) && !expanded[f.key] && toggleExpand(f.key)"
          >
            <template v-if="expanded[f.key] || !isLongValue(f)">
              {{ display(f) }}
            </template>
            <template v-else>
              <span class="rd-clamp-2">{{ display(f) }}</span>
              <span class="rd-toggle" @click.stop="toggleExpand(f.key)">展开</span>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row-detail {
  padding: 8px 12px 10px;
  background: var(--ziwi-bg-light, #f7f8fa);
  border-top: 1px dashed var(--ziwi-border, #ebedf0);
}

/* ---------- header ---------- */
.rd-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.4;
}
.rd-header-summary {
  font-weight: 600;
  color: var(--ziwi-text-primary, #323233);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rd-header-count {
  flex-shrink: 0;
  margin-left: 8px;
  color: var(--ziwi-text-muted, #969799);
  font-weight: 400;
}

/* ---------- grid wrapper (horizontal scroll) ---------- */
.rd-grid-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

/* ---------- grid ---------- */
.rd-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 6px 12px;
  min-width: 100%;
}

.rd-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 120px;
}

.rd-label {
  font-size: 11px;
  color: var(--ziwi-text-muted, #969799);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rd-value {
  font-size: 13px;
  color: var(--ziwi-text-primary, #323233);
  word-break: break-all;
  line-height: 1.5;
}

/* 空值态 */
.rd-empty {
  color: var(--ziwi-text-muted, #c8c9cc);
}

/* 长文本折叠：最多显示 2 行 */
.rd-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 展开按钮 */
.rd-toggle {
  color: var(--ziwi-primary, #1989fa);
  cursor: pointer;
  font-size: 11px;
  margin-left: 4px;
  white-space: nowrap;
}

/* 移动端降级：列最小宽度大一点 */
@media (max-width: 480px) {
  .rd-grid {
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  }
}
</style>
