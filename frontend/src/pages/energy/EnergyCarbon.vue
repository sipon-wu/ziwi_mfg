<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import dayjs from 'dayjs'

// 碳管理：基础骨架 + 图表占位，数据接 /energy/carbon/accounting
const startDate = ref(dayjs().startOf('month').format('YYYY-MM-DD'))
const endDate = ref(dayjs().format('YYYY-MM-DD'))
const totalCo2 = ref<number | string>('—')
const breakdown = ref<any[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await get<any>('/energy/carbon/accounting', {
      start_date: startDate.value,
      end_date: endDate.value,
    })
    const d = r.data ?? r
    totalCo2.value = d.total_co2_ton ?? '—'
    breakdown.value = d.source_breakdown || []
  } catch {
    totalCo2.value = '—'
    breakdown.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <van-cell-group title="碳核算范围">
      <van-field v-model="startDate" label="开始日期" type="date" />
      <van-field v-model="endDate" label="结束日期" type="date" />
    </van-cell-group>

    <div style="padding:12px 16px;">
      <van-button type="primary" size="small" :loading="loading" @click="load">查询碳排放</van-button>
    </div>

    <van-cell-group title="碳排放汇总">
      <van-cell title="总碳排放(吨 CO₂e)" :value="String(totalCo2)" />
      <van-cell v-for="(b, i) in breakdown" :key="i" :title="b.energy_type" :value="`${b.total_emission} kg`" />
    </van-cell-group>

    <van-cell-group title="碳管理" style="margin-top:12px;">
      <van-cell title="碳资产" label="图表占位（碳资产趋势）" />
    </van-cell-group>
  </div>
</template>
