<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:70vh; gap:16px; padding:0 24px; text-align:center;">
    <div style="font-size:64px; font-weight:700; color:var(--color-text-tertiary); line-height:1;">404</div>
    <div style="font-size:15px; color:var(--color-text-secondary);">页面不存在或已被移除</div>
    <van-button type="primary" @click="router.push('/dashboard')">返回首页</van-button>
  </div>
</template>
