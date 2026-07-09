<script setup lang="ts">
import { ref } from 'vue'
import { get } from '@/api/client'
import { showToast } from 'vant'
import dayjs from 'dayjs'

const date = ref(dayjs().format('YYYY-MM-DD'))
const report = ref<WorkReport | null>(null)
const loading = ref(false)

async function query() {
  loading.value = true
  try {
    report.value = await get('/reports/daily', { report_date: date.value })
  } catch { showToast('获取报表失败') }
  finally { loading.value = false }
}
</script>

<template>
  <div>
    <van-nav-bar title="生产日报" />
    <van-cell-group>
      <van-field v-model="date" label="日期" type="date" @change="query" />
    </van-cell-group>
    <van-button block type="primary" @click="query" :loading="loading" style="margin:8px 0">查询</van-button>
    <div v-if="report">
      <van-cell-group title="汇总">
        <van-cell title="总产出" :value="`${report.total_output} 件`" />
        <van-cell title="不良数" :value="`${report.total_scrap} 件`" />
        <van-cell title="总工时" :value="`${report.total_hours} 小时`" />
      </van-cell-group>
      <van-cell-group title="明细">
        <van-cell v-for="row in report.rows || []" :key="row.wo_no"
          :title="row.wo_no" :label="`${row.product_name} | 产出:${row.total_output} 不良:${row.total_scrap} 工时:${row.total_hours}h`" />
        <van-cell v-if="!report.rows?.length" title="暂无数据" />
      </van-cell-group>
    </div>
  </div>
</template>
