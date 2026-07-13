<script setup lang="ts">
import { ref, computed } from 'vue'
import dayjs from 'dayjs'
import SelectField from '@/components/SelectField.vue'
import type { FieldDef, Operator, ResourceSearchConfig, SearchCondition } from '@/types/search'
import { OPERATOR_LABELS, defaultOperatorsFor } from '@/types/search'

const props = defineProps<{
  config: ResourceSearchConfig
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [v: boolean]
  search: [conditions: SearchCondition[]]
  reset: []
}>()

let uidSeq = 0
function nextUid(): string {
  uidSeq += 1
  return `d_${uidSeq}_${Date.now().toString(36)}`
}

const draft = ref<SearchCondition[]>([])

function operatorsFor(fieldKey: string): Operator[] {
  const def = props.config.searchFields.find((f) => f.key === fieldKey)
  return def?.operators && def.operators.length
    ? def.operators
    : defaultOperatorsFor(def?.type || 'string')
}

function optionsForOperators(fieldKey: string) {
  return operatorsFor(fieldKey).map((op) => ({ label: OPERATOR_LABELS[op], value: op }))
}

function fieldOptions() {
  return props.config.searchFields.map((f) => ({ label: f.label, value: f.key }))
}

function defOf(fieldKey: string): FieldDef | undefined {
  return props.config.searchFields.find((f) => f.key === fieldKey)
}

function makeCondition(fieldKey?: string): SearchCondition {
  const key = fieldKey || props.config.searchFields[0]?.key || ''
  const op = operatorsFor(key)[0] || 'EQ'
  return { uid: nextUid(), field: key, operator: op, value: undefined, value2: undefined }
}

function addCondition() {
  draft.value.push(makeCondition())
}
function removeCondition(idx: number) {
  draft.value.splice(idx, 1)
}
function onFieldChange(cond: SearchCondition) {
  const ops = operatorsFor(cond.field)
  if (!ops.includes(cond.operator)) {
    cond.operator = ops[0] || 'EQ'
  }
  cond.value = undefined
  cond.value2 = undefined
}
function onOperatorChange(cond: SearchCondition) {
  if (cond.operator === 'IS_EMPTY' || cond.operator === 'NOT_EMPTY') {
    cond.value = undefined
    cond.value2 = undefined
  } else if (cond.operator !== 'BETWEEN') {
    cond.value2 = undefined
  }
}

function onClose() {
  emit('update:show', false)
}
function onSearch() {
  emit('search', draft.value.map((c) => ({ ...c })))
  emit('update:show', false)
}
function onReset() {
  draft.value = []
  emit('reset')
  emit('update:show', false)
}

// ---------- 值输入：enum / boolean 用 SelectField，日期用日期选择器 ----------
function enumOptions(fieldKey: string) {
  const def = defOf(fieldKey)
  return (def?.options || []).map((o) => ({ label: o.label, value: o.value }))
}
function booleanOptions() {
  return [
    { label: '是', value: true },
    { label: '否', value: false },
  ]
}

const hasValue = (op: Operator) => op !== 'IS_EMPTY' && op !== 'NOT_EMPTY'
const needsTwo = (op: Operator) => op === 'BETWEEN'

// 日期选择器
const dateTarget = ref<{ uid: string; which: 'value' | 'value2' } | null>(null)
const dateTemp = ref<number[]>([2024, 1, 1])

function fmtDate(arr: number[]): string {
  const [y, m, d] = arr
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}
function parseDate(str?: any): number[] {
  if (!str) return [dayjs().year(), dayjs().month() + 1, dayjs().date()]
  const parts = String(str).slice(0, 10).split('-').map(Number)
  if (parts.length === 3 && !parts.some(Number.isNaN)) return parts
  return [dayjs().year(), dayjs().month() + 1, dayjs().date()]
}
function openDate(cond: SearchCondition, which: 'value' | 'value2') {
  dateTarget.value = { uid: cond.uid, which }
  dateTemp.value = parseDate(which === 'value' ? cond.value : cond.value2)
}
function onDateConfirm() {
  if (!dateTarget.value) return
  const { uid, which } = dateTarget.value
  const cond = draft.value.find((c) => c.uid === uid)
  if (cond) cond[which] = fmtDate(dateTemp.value)
  dateTarget.value = null
}

const fieldLabel = (key: string) => defOf(key)?.label || key
</script>

<template>
  <van-popup :show="show" position="bottom" round :style="{ height: '80%' }" @update:show="emit('update:show', $event)">
    <div class="asp">
      <div class="asp-header">
        <span class="asp-title">高级检索</span>
        <van-icon name="cross" size="20" @click="onClose" />
      </div>

      <div class="asp-body">
        <div v-if="draft.length === 0" class="asp-empty">暂无检索条件，点击下方"添加条件"开始</div>

        <div v-for="(cond, idx) in draft" :key="cond.uid" class="asp-row">
          <div class="asp-row-head">
            <span class="asp-idx">条件 {{ idx + 1 }}</span>
            <van-icon name="delete-o" size="18" color="#ee0a24" @click="removeCondition(idx)" />
          </div>

          <div class="asp-line">
            <div class="asp-cell">
              <span class="asp-clabel">字段</span>
              <SelectField
                :model-value="cond.field"
                :options="fieldOptions()"
                placeholder="选择字段"
                @update:model-value="(v: any) => { cond.field = v; onFieldChange(cond) }"
                @change="(v: any) => { cond.field = v; onFieldChange(cond) }"
              />
            </div>
            <div class="asp-cell">
              <span class="asp-clabel">条件</span>
              <SelectField
                :model-value="cond.operator"
                :options="optionsForOperators(cond.field)"
                placeholder="选择条件"
                @update:model-value="(v: any) => { cond.operator = v; onOperatorChange(cond) }"
                @change="(v: any) => { cond.operator = v; onOperatorChange(cond) }"
              />
            </div>
          </div>

          <div v-if="hasValue(cond.operator)" class="asp-line">
            <template v-if="defOf(cond.field)?.type === 'enum'">
              <div class="asp-cell asp-cell--full">
                <SelectField
                  :model-value="cond.value"
                  :options="enumOptions(cond.field)"
                  placeholder="选择值"
                  @update:model-value="(v: any) => (cond.value = v)"
                />
              </div>
            </template>

            <template v-else-if="defOf(cond.field)?.type === 'boolean'">
              <div class="asp-cell asp-cell--full">
                <SelectField
                  :model-value="cond.value"
                  :options="booleanOptions()"
                  placeholder="选择值"
                  @update:model-value="(v: any) => (cond.value = v)"
                />
              </div>
            </template>

            <template v-else-if="defOf(cond.field)?.type === 'date'">
              <div class="asp-cell">
                <van-field
                  :model-value="cond.value"
                  readonly
                  placeholder="起始日期"
                  @click="openDate(cond, 'value')"
                />
              </div>
              <div v-if="needsTwo(cond.operator)" class="asp-cell">
                <van-field
                  :model-value="cond.value2"
                  readonly
                  placeholder="结束日期"
                  @click="openDate(cond, 'value2')"
                />
              </div>
            </template>

            <template v-else-if="defOf(cond.field)?.type === 'number'">
              <div class="asp-cell">
                <van-field v-model.number="cond.value" type="number" placeholder="数值" />
              </div>
              <div v-if="needsTwo(cond.operator)" class="asp-cell">
                <van-field v-model.number="cond.value2" type="number" placeholder="至" />
              </div>
            </template>

            <template v-else>
              <div class="asp-cell">
                <van-field v-model="cond.value" type="text" placeholder="输入值" />
              </div>
              <div v-if="needsTwo(cond.operator)" class="asp-cell">
                <van-field v-model="cond.value2" type="text" placeholder="至" />
              </div>
            </template>
          </div>
        </div>
      </div>

      <div class="asp-footer">
        <van-button block plain type="primary" @click="addCondition">+ 添加条件</van-button>
        <div class="asp-footer-actions">
          <van-button type="default" @click="onReset">重置</van-button>
          <van-button type="primary" @click="onSearch">查询</van-button>
        </div>
      </div>
    </div>
  </van-popup>

  <van-popup v-if="dateTarget" :show="!!dateTarget" position="bottom" @update:show="dateTarget = null">
    <van-date-picker v-model="dateTemp" title="选择日期"
      :min-date="new Date(2015, 0, 1)" :max-date="new Date(2035, 11, 31)"
      @confirm="onDateConfirm" @cancel="dateTarget = null" />
  </van-popup>
</template>

<style scoped>
.asp {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}
.asp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #ebedf0;
}
.asp-title {
  font-size: 16px;
  font-weight: 600;
}
.asp-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}
.asp-empty {
  text-align: center;
  color: #969799;
  font-size: 13px;
  padding: 40px 0;
}
.asp-row {
  border: 1px solid #ebedf0;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #fafafa;
}
.asp-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.asp-idx {
  font-size: 13px;
  color: #646566;
  font-weight: 600;
}
.asp-line {
  display: flex;
  gap: 10px;
}
.asp-line + .asp-line {
  margin-top: 8px;
}
.asp-cell {
  flex: 1;
  min-width: 0;
}
.asp-cell--full {
  flex: 1 1 100%;
}
.asp-clabel {
  display: block;
  font-size: 12px;
  color: #969799;
  margin-bottom: 2px;
}
.asp-footer {
  border-top: 1px solid #ebedf0;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.asp-footer-actions {
  display: flex;
  gap: 12px;
}
.asp-footer-actions .van-button {
  flex: 1;
}
</style>
