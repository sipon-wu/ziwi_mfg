<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast } from 'vant'
import { get, post } from '@/api/client'

const form = ref({ source_location_id: 0, target_location_id: 0, material_id: 0, batch_no: '', quantity: 1, unit: '个', remark: '' })
const submitting = ref(false)
const materials = ref<any[]>([])
const locations = ref<any[]>([])
const warehouses = ref<any[]>([])
const selectedWh = ref<any>(null)
const showWhPicker = ref(false)
const showMatPicker = ref(false)
const showSrcLocPicker = ref(false)
const showTgtLocPicker = ref(false)

/**
 * ★ 每个 Picker 都要有自己的 `v-model`（选中值数组），且必须在数据到位时**种子**进去。
 *
 * 为什么：Vant 4 的 `Picker.mjs:34` 是 `ref(props.modelValue.slice(0))` —— 选中值
 * 完全来自 `modelValue`，`makeArrayProp()` 的默认值是 `[]`。不绑 `v-model` 时，
 * 「不滚动、直接点确认」（也就是选第一项，最常见的一次操作）走的是
 * `selectedOptions[0]` → `undefined` → 处理函数拿到的值是空，界面看着高亮第一项、
 * 实际什么都没选中。本人 2026-11-08 在浏览器里实测：点确认后弹层关了、字段仍为空。
 *
 * 种子用「列表第一项」，与 Picker 把它们显示成高亮的视觉状态保持一致。
 */
const whPicker = ref<any[]>([])
const matPicker = ref<any[]>([])
const srcLocPicker = ref<any[]>([])
const tgtLocPicker = ref<any[]>([])
function seed(target: any, list: any[] | null | undefined) {
  target.value = list && list.length ? [list[0].id] : []
}

async function loadWarehouses() {
  warehouses.value = await get<any[]>('/wms/warehouses/all/active')
  seed(whPicker, warehouses.value)
}
async function loadMaterials() {
  materials.value = await get<any[]>('/wms/materials', { page: 1, page_size: 100 }).then(r => (r as any).items)
  seed(matPicker, materials.value)
}
async function loadLocations() {
  if (!selectedWh.value) return
  locations.value = await get<any[]>(`/wms/warehouses/${selectedWh.value}/locations`)
  seed(srcLocPicker, locations.value)
  seed(tgtLocPicker, locations.value)
}

/**
 * ★ 关弹层必须写在处理函数里，别写成「函数名 + 分号 + 赋值」那种多语句内联处理器：
 *   Vue 对多语句内联处理器按**表达式**求值 —— `onWhConfirm` 只被读到、不会被调用，
 *   只有后半句赋值生效。结果就是弹层关了、选中值从没写进去，不报错也不告警，
 *   表现为「选完像没选」。2026-11-09 在 staging 浏览器实测确认（弹层关闭、字段为空、0 错）。
 */
function onWhConfirm({ selectedOptions }: any) {
  selectedWh.value = selectedOptions[0]?.value
  showWhPicker.value = false
  loadLocations()
}
function onMatConfirm({ selectedOptions }: any) {
  form.value.material_id = selectedOptions[0]?.value || 0
  showMatPicker.value = false
}
function onSrcLocConfirm({ selectedOptions }: any) {
  form.value.source_location_id = selectedOptions[0]?.value || 0
  showSrcLocPicker.value = false
}
function onTgtLocConfirm({ selectedOptions }: any) {
  form.value.target_location_id = selectedOptions[0]?.value || 0
  showTgtLocPicker.value = false
}

async function handleSubmit() {
  if (!form.value.source_location_id || !form.value.target_location_id) { showToast('请选择源库位和目标库位'); return }
  if (form.value.source_location_id === form.value.target_location_id) { showToast('源库位与目标库位不能相同'); return }
  submitting.value = true
  try {
    await post('/wms/inventory/stock-move', form.value)
    showToast('库存移动成功')
    form.value.quantity = 1; form.value.remark = ''
  } catch { showToast('移动失败') }
  finally { submitting.value = false }
}

onMounted(() => { loadWarehouses(); loadMaterials() })
</script>

<template>
  <div>
    <van-nav-bar title="库存移动" />
    <van-form @submit="handleSubmit" style="padding:16px">
      <van-field name="warehouse" label="目标仓库" :model-value="selectedWh ? (warehouses.find(w => w.id === selectedWh)?.name || '') : ''" is-link readonly @click="showWhPicker = true" />
      <van-field name="material" label="物料" :model-value="materials.find(m => m.id === form.material_id)?.code || ''" is-link readonly @click="showMatPicker = true" />
      <van-field name="source_location" label="源库位" :model-value="locations.find(l => l.id === form.source_location_id)?.location_code || ''" is-link readonly @click="showSrcLocPicker = true" />
      <van-field name="target_location" label="目标库位" :model-value="locations.find(l => l.id === form.target_location_id)?.location_code || ''" is-link readonly @click="showTgtLocPicker = true" />
      <van-field v-model.number="form.quantity" label="移动数量" type="digit" />
      <van-field v-model="form.unit" label="单位" />
      <van-field v-model="form.batch_no" label="批号" />
      <van-field v-model="form.remark" label="备注" type="textarea" rows="2" />
      <div style="margin-top:16px"><van-button round block type="primary" native-type="submit" :loading="submitting">确认移动</van-button></div>
    </van-form>

    <van-popup v-model:show="showWhPicker" position="bottom">
      <van-picker v-model="whPicker" :columns="warehouses.map(w => ({ text: w.name, value: w.id }))" @confirm="onWhConfirm" @cancel="showWhPicker = false" />
    </van-popup>
    <van-popup v-model:show="showMatPicker" position="bottom">
      <van-picker v-model="matPicker" :columns="materials.map(m => ({ text: `${m.code} - ${m.name}`, value: m.id }))" @confirm="onMatConfirm" @cancel="showMatPicker = false" />
    </van-popup>
    <van-popup v-model:show="showSrcLocPicker" position="bottom">
      <van-picker v-model="srcLocPicker" :columns="locations.map(l => ({ text: l.location_code, value: l.id }))" @confirm="onSrcLocConfirm" @cancel="showSrcLocPicker = false" />
    </van-popup>
    <van-popup v-model:show="showTgtLocPicker" position="bottom">
      <van-picker v-model="tgtLocPicker" :columns="locations.map(l => ({ text: l.location_code, value: l.id }))" @confirm="onTgtLocConfirm" @cancel="showTgtLocPicker = false" />
    </van-popup>
  </div>
</template>
