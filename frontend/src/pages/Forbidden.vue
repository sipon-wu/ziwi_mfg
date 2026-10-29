<script setup lang="ts">
/**
 * 403 无权限页（S2）
 *
 * 触发场景：
 * 1. 前端路由守卫发现当前用户缺少 meta.perm 要求的权限码
 * 2. 后端 permission_guard 返回 403（{code: '403-0001', required: '...'}）
 *
 * 页面会展示"缺少哪个权限码"，便于运维定位应给该角色补哪条权限，
 * 而不是只丢一个"无权限"让人无从下手。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const requestedPath = computed(() => (route.query.from as string) || '')
const requiredPerm = computed(() => (route.query.perm as string) || '')

const showDetail = ref(false)
</script>

<template>
  <div class="forbidden">
    <div class="code">403</div>
    <div class="title">没有访问权限</div>
    <div class="desc">
      当前账号的角色未被授予该页面的访问权限。如需开通，请联系本租户管理员在
      「系统管理 → 角色权限」中为此角色勾选对应权限。
    </div>

    <div class="actions">
      <van-button type="primary" @click="router.push('/dashboard')">返回首页</van-button>
      <van-button plain @click="showDetail = !showDetail">
        {{ showDetail ? '收起详情' : '查看详情' }}
      </van-button>
    </div>

    <div v-if="showDetail" class="detail">
      <div class="row"><span>请求路径</span><code>{{ requestedPath || '—' }}</code></div>
      <div class="row"><span>所需权限</span><code>{{ requiredPerm || '（未在路由上声明）' }}</code></div>
    </div>
  </div>
</template>

<style scoped>
.forbidden {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  gap: 12px;
  padding: 0 24px;
  text-align: center;
}
.code {
  font-size: 64px;
  font-weight: 700;
  color: var(--color-text-tertiary, #c8c9cc);
  line-height: 1;
}
.title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary, #323233);
}
.desc {
  max-width: 520px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-secondary, #969799);
}
.actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}
.detail {
  margin-top: 12px;
  padding: 12px 16px;
  min-width: 320px;
  border-radius: 8px;
  background: var(--color-fill-quaternary, #f7f8fa);
  text-align: left;
}
.row {
  display: flex;
  gap: 12px;
  font-size: 12px;
  line-height: 2;
  color: var(--color-text-secondary, #969799);
}
.row span {
  min-width: 64px;
}
.row code {
  color: var(--color-text-primary, #323233);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all;
}
</style>
