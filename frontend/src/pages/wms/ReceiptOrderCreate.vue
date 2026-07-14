<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast } from 'vant'
import { get, post } from '@/api/client'

const router = useRouter()
const submitting = ref(false)

interface WarehouseOption {
  value: number
  label: string
}

const form = ref({
  receipt_no: '',
  receipt_type: 'purchase',
  source_type: '',
  source_doc_no: '',
  warehouse_id: null as number | null,
  supplier_id: null as number | null,
})

const showWhPicker = ref(false)

const warehouseOptions = ref<WarehouseOption[]>([])
const typeOptions = [
  { value: 'purchase', label: '采购入库' },
  { value: '生产入库', label: '生产入库' },
  { value: '退货入库', label: '退货入库' },
  { value: 'transfer', label: '调拨入库' },
]

const warehouseLabel = computed(() => {
  const found = warehouseOptions.value.find((w) => w.value === form.value.warehouse_id)
  return found ? found.label : form.value.warehouse_id ? `ID: ${form.value.warehouse_id}` : ''
})

onMounted(async () => {
  try {
    const warehouses: any[] = await get('/wms/warehouses/all/active')
    warehouseOptions.value = (warehouses || []).map((w: any) => ({ value: w.id, label: w.name }))
  } catch {
    // 仓库列表加载失败，用户可手动输入 ID
  }
})

async function onPickWarehouse() {
  showWhPicker.value = true
}

function onWhConfirm({ selectedOptions }: { selectedOptions: Array<{ value: number }> }) {
  form.value.warehouse_id = selectedOptions[0].value
  showWhPicker.value = false
}

async function onSubmit() {
  if (!form.value.receipt_no) { showToast('请输入入库单号'); return }
  if (!form.value.warehouse_id) { showToast('请选择仓库'); return }

  submitting.value = true
  showLoadingToast({ message: '创建中...', forbidClick: true })
  try {
    const body: Record<string, any> = { ...form.value }
    if (!body.source_type) delete body.source_type
    if (!body.source_doc_no) delete body.source_doc_no
    if (!body.supplier_id) delete body.supplier_id
    body.items = []

    await post('/wms/receipt-orders', body)
    closeToast()
    showToast('创建成功')
    router.push('/wms/receipt-orders')
  } catch {
    closeToast()
    showToast('创建失败')
  } finally {
    submitting.value = false
  }
}

function goBack() { router.push('/wms/receipt-orders') }
</script>

<template>
  <div>
    <van-nav-bar title="新增入库单" left-arrow @click-left="goBack" />

    <van-form @submit="onSubmit">
      <van-cell-group title="入库单信息">
        <van-field
          v-model="form.receipt_no"
          label="入库单号"
          placeholder="必填，如 PO-2024-001"
          required
          :rules="[{ required: true, message: '请输入入库单号' }]"
        />
        <van-field name="receipt_type" label="入库类型">
          <template #input>
            <van-radio-group v-model="form.receipt_type" direction="horizontal">
              <van-radio v-for="t in typeOptions" :key="t.value" :name="t.value">
                {{ t.label }}
              </van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field
          v-model="form.source_type"
          label="来源类型"
          placeholder="选填，如采购、生产"
        />
        <van-field
          v-model="form.source_doc_no"
          label="来源单号"
          placeholder="选填，关联的来源单据号"
        />
        <van-field
          v-model="warehouseLabel"
          is-link
          label="目标仓库"
          placeholder="点击选择仓库"
          required
          :rules="[{ required: true, message: '请选择仓库' }]"
          @click="onPickWarehouse"
          readonly
        />
        <van-field
          v-model="form.supplier_id"
          label="供应商ID"
          placeholder="选填"
          type="digit"
        />
      </van-cell-group>

      <div style="padding: 16px">
        <van-button block type="primary" native-type="submit" :loading="submitting">
          创建入库单
        </van-button>
      </div>
    </van-form>

    <van-popup v-model:show="showWhPicker" position="bottom">
      <van-picker
        :columns="warehouseOptions.map((w) => ({ text: w.label, value: w.value }))"
        @confirm="onWhConfirm"
        @cancel="showWhPicker = false"
      />
    </van-popup>
  </div>
</template>
