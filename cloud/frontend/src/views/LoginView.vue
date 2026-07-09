<template>
  <AuthLayout>
    <form @submit.prevent="handleLogin" class="space-y-5">
      <h2 class="text-xl font-semibold text-gray-800 text-center">登录</h2>

      <div v-if="error" class="bg-red-50 text-red-600 text-sm px-4 py-2 rounded-lg">
        {{ error }}
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">邮箱</label>
        <input
          v-model="email"
          type="email"
          required
          placeholder="your@email.com"
          class="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
        <input
          v-model="password"
          type="password"
          required
          placeholder="&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;"
          class="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
        />
      </div>

      <button
        type="submit"
        :disabled="loading"
        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-lg transition disabled:opacity-50"
      >
        {{ loading ? '登录中...' : '登录' }}
      </button>

      <p class="text-center text-sm text-gray-500">
        还没有账号？
        <router-link to="/register" class="text-blue-600 hover:underline">注册</router-link>
      </p>
    </form>
  </AuthLayout>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import AuthLayout from "../components/AuthLayout.vue";

const router = useRouter();
const store = useAuthStore();

const email = ref("");
const password = ref("");
const loading = ref(false);
const error = ref("");

async function handleLogin() {
  loading.value = true;
  error.value = "";
  try {
    await store.login(email.value, password.value);
    router.push("/");
  } catch (e: any) {
    error.value = e?.response?.data?.detail?.message || "登录失败，请检查邮箱和密码";
  } finally {
    loading.value = false;
  }
}
</script>
