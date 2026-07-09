<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <div class="login-logo">☁</div>
        <h1 class="login-title">知微平台运营中心</h1>
        <p class="login-subtitle">admin.ziwi.cn 管理后台</p>
      </div>

      <div class="login-body">
        <div class="form-group">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="username"
            type="text"
            class="form-input"
            placeholder="请输入用户名"
            @keyup.enter="handleLogin"
            :disabled="loading"
          />
        </div>
        <div class="form-group">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            class="form-input"
            placeholder="请输入密码"
            @keyup.enter="handleLogin"
            :disabled="loading"
          />
        </div>

        <div v-if="errorMsg" class="login-error">{{ errorMsg }}</div>

        <button
          class="btn-primary login-btn"
          @click="handleLogin"
          :disabled="loading"
        >
          <span v-if="loading" class="btn-loading"></span>
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </div>

      <div class="login-footer">
        <span class="copyright">© 2024 Ziwi Cloud. All rights reserved.</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin(): Promise<void> {
  if (!username.value.trim() || !password.value.trim()) {
    errorMsg.value = '请输入用户名和密码'
    return
  }

  loading.value = true
  errorMsg.value = ''

  try {
    await auth.login(username.value.trim(), password.value.trim())
    router.push('/')
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.message || err?.message || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, var(--ziwi-primary) 0%, var(--ziwi-primary-dark) 50%, var(--ziwi-primary-darker) 100%);
  position: relative;
  overflow: hidden;
}

.login-page::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(ellipse at 30% 50%, rgba(13, 115, 119, 0.12) 0%, transparent 50%),
    radial-gradient(ellipse at 70% 50%, rgba(13, 115, 119, 0.08) 0%, transparent 50%);
  pointer-events: none;
}

.login-card {
  position: relative;
  width: 400px;
  max-width: 90vw;
  background: rgba(255, 255, 255, 0.95);
  border-radius: var(--ziwi-radius-xl);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}

.login-header {
  text-align: center;
  padding: 40px 40px 0;
}

.login-logo {
  font-size: 48px;
  margin-bottom: 12px;
}

.login-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--ziwi-text-primary);
  margin-bottom: 6px;
}

.login-subtitle {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-muted);
  margin-bottom: 0;
}

.login-body {
  padding: 32px 40px;
}

.login-body .form-group label {
  font-size: var(--ziwi-font-size-md);
  font-weight: 500;
  color: var(--ziwi-text-secondary);
  margin-bottom: 8px;
  display: block;
}

.login-body .form-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-lg);
  font-size: var(--ziwi-font-size-lg);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  background: var(--ziwi-bg-light);
  box-sizing: border-box;
}

.login-body .form-input:focus {
  border-color: var(--ziwi-primary);
  box-shadow: 0 0 0 3px rgba(13, 115, 119, 0.1);
  background: var(--ziwi-bg-white);
}

.login-btn {
  width: 100%;
  padding: 10px 0;
  font-size: 15px;
  border-radius: var(--ziwi-radius-lg);
  margin-top: 4px;
  justify-content: center;
}

.btn-loading {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: var(--ziwi-text-white);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.login-footer {
  text-align: center;
  padding: 0 40px 24px;
}

.copyright {
  font-size: var(--ziwi-font-size-sm);
  color: #bbb;
}
</style>
