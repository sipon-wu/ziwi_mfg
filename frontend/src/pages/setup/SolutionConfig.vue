<script setup lang="ts">
import { useRouter } from 'vue-router'
import { showToast } from 'vant'

const router = useRouter()

// 双路径配置入口（产品方案第六章）
const quickPaths = [
  { label: '快速开通生产管理', desc: '工单 / 报工 / 排产 一键启用', to: '/work-orders' },
  { label: '快速接入设备', desc: '设备台账 / 维保计划', to: '/equipment' },
  { label: '快速启用能碳', desc: '能耗设备 / 碳核算', to: '/energy' },
]

const detailedPaths = [
  { label: '基础数据配置', desc: '工序 / 工作中心 / 工艺路线 / 产品', to: '/basics/operations' },
  { label: '品质体系配置', desc: '检验标准 / SPC / PPAP / FMEA', to: '/quality' },
  { label: '仓储与供应链', desc: 'WMS 仓库 / 物料 / 库存', to: '/wms/warehouse-tree' },
  { label: '试产与实验室', desc: '试产管理 / 实验委托', to: '/trials' },
  { label: '系统配置', desc: '模块与许可证', to: '/system/config' },
]

function go(to: string) {
  router.push(to)
}

function startAssessment() {
  showToast('数字化水平自评即将上线')
}
</script>

<template>
  <div>
    <van-cell-group title="方案配置入口">
      <van-cell title="ziwi.cn 方案配置" label="按业务场景选择配置路径，最短路径可快速上线，详细路径覆盖全模块" />
    </van-cell-group>

    <div style="padding:16px;">
      <h3 style="margin:0 0 8px; font-size:15px; color:var(--color-text-primary);">最短路径（快速上线）</h3>
      <van-cell
        v-for="p in quickPaths" :key="p.label"
        :title="p.label" :label="p.desc" is-link @click="go(p.to)"
      />
    </div>

    <div style="padding:0 16px 16px;">
      <h3 style="margin:0 0 8px; font-size:15px; color:var(--color-text-primary);">详细路径（完整配置）</h3>
      <van-cell
        v-for="p in detailedPaths" :key="p.label"
        :title="p.label" :label="p.desc" is-link @click="go(p.to)"
      />
    </div>

    <div style="margin:8px 16px 16px;">
      <van-button block type="primary" @click="startAssessment">开始数字化水平自评</van-button>
    </div>
  </div>
</template>
