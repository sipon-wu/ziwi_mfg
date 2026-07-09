<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { showToast } from 'vant'

const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) { showToast('请输入用户名和密码'); return }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    showToast('登录成功')
    router.push('/cockpit')
  } catch (e: any) {
    showToast(e.response?.data?.detail?.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <img src="/ziwilogo.png" alt="ziwi" class="login-logo-img" />
        <span class="login-brand">知微制造</span>
      </div>
      <p class="login-subtitle">ziwi SaaS 可配置数字化平台</p>
      <van-form @submit="handleLogin">
        <van-field v-model="username" label="用户名" placeholder="请输入用户名" :rules="[{ required: true }]" />
        <van-field v-model="password" type="password" label="密码" placeholder="请输入密码" :rules="[{ required: true }]" />
        <div style="margin:16px 0">
          <van-button round block type="primary" native-type="submit" :loading="loading">
            登 录
          </van-button>
        </div>
      </van-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, var(--ziwi-primary) 0%, var(--ziwi-primary-dark) 50%, var(--ziwi-primary-darker) 100%);
}
.login-card {
  width: 380px;
  padding: 40px;
  background: var(--ziwi-bg-white);
  border-radius: var(--ziwi-radius-xl);
  box-shadow: var(--ziwi-shadow-lg);
  text-align: center;
}
.login-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 8px;
}
.login-logo-img {
  width: 40px;
  height: 40px;
  object-fit: contain;
}
.login-brand {
  font-size: 22px;
  font-weight: 700;
  color: var(--ziwi-primary);
}
.login-subtitle {
  color: var(--ziwi-text-muted);
  margin-bottom: 24px;
  font-size: 14px;
}
</style>
