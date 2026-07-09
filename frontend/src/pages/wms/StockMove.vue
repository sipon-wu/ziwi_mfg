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

async function loadWarehouses() { warehouses.value = await get<any[]>('/wms/warehouses/all/active') }
async function loadMaterials() { materials.value = await get<any[]>('/wms/materials', { page: 1, page_size: 200 }).then(r => (r as any).items) }
async function loadLocations() {
  if (!selectedWh.value) return
  locations.value = await get<any[]>(`/wms/warehouses/${selectedWh.value}/locations`)
}

function onWhConfirm({ selectedOptions }: any) {
  selectedWh.value = selectedOptions[0]?.value
  loadLocations()
}
function onMatConfirm({ selectedOptions }: any) {
  form.value.material_id = selectedOptions[0]?.value || 0
}
function onSrcLocConfirm({ selectedOptions }: any) {
  form.value.source_location_id = selectedOptions[0]?.value || 0
}
function onTgtLocConfirm({ selectedOptions }: any) {
  form.value.target_location_id = selectedOptions[0]?.value || 0
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
      <van-field name="warehouse" label="目标仓库" :value="selectedWh ? (warehouses.find(w => w.id === selectedWh)?.name || '') : ''" is-link @click="showWhPicker = true" />
      <van-field name="material" label="物料" :value="materials.find(m => m.id === form.material_id)?.code || ''" is-link @click="showMatPicker = true" />
      <van-field name="source_location" label="源库位" :value="locations.find(l => l.id === form.source_location_id)?.location_code || ''" is-link @click="showSrcLocPicker = true" />
      <van-field name="target_location" label="目标库位" :value="locations.find(l => l.id === form.target_location_id)?.location_code || ''" is-link @click="showTgtLocPicker = true" />
      <van-field v-model.number="form.quantity" label="移动数量" type="digit" />
      <van-field v-model="form.unit" label="单位" />
      <van-field v-model="form.batch_no" label="批号" />
      <van-field v-model="form.remark" label="备注" type="textarea" rows="2" />
      <div style="margin-top:16px"><van-button round block type="primary" native-type="submit" :loading="submitting">确认移动</van-button></div>
    </van-form>

    <van-popup v-model:show="showWhPicker" position="bottom">
      <van-picker :columns="warehouses.map(w => ({ text: w.name, value: w.id }))" @confirm="onWhConfirm; showWhPicker = false" @cancel="showWhPicker = false" />
    </van-popup>
    <van-popup v-model:show="showMatPicker" position="bottom">
      <van-picker :columns="materials.map(m => ({ text: `${m.code} - ${m.name}`, value: m.id }))" @confirm="onMatConfirm; showMatPicker = false" @cancel="showMatPicker = false" />
    </van-popup>
    <van-popup v-model:show="showSrcLocPicker" position="bottom">
      <van-picker :columns="locations.map(l => ({ text: l.location_code, value: l.id }))" @confirm="onSrcLocConfirm; showSrcLocPicker = false" @cancel="showSrcLocPicker = false" />
    </van-popup>
    <van-popup v-model:show="showTgtLocPicker" position="bottom">
      <van-picker :columns="locations.map(l => ({ text: l.location_code, value: l.id }))" @confirm="onTgtLocConfirm; showTgtLocPicker = false" @cancel="showTgtLocPicker = false" />
    </van-popup>
  </div>
</template>
