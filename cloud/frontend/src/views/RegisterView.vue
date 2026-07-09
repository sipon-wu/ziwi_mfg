<template>
  <AuthLayout>
    <form @submit.prevent="handleRegister" class="space-y-5">
      <h2 class="text-xl font-semibold text-gray-800 text-center">注册</h2>

      <div v-if="error" class="bg-red-50 text-red-600 text-sm px-4 py-2 rounded-lg">
        {{ error }}
      </div>
      <div v-if="success" class="bg-green-50 text-green-600 text-sm px-4 py-2 rounded-lg">
        {{ success }}
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">显示名称</label>
        <input
          v-model="displayName"
          type="text"
          required
          placeholder="您的姓名"
          class="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
        />
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
          minlength="8"
          placeholder="至少8位"
          class="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
        />
      </div>

      <button
        type="submit"
        :disabled="loading"
        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-lg transition disabled:opacity-50"
      >
        {{ loading ? '注册中...' : '注册' }}
      </button>

      <p class="text-center text-sm text-gray-500">
        已有账号？
        <router-link to="/login" class="text-blue-600 hover:underline">登录</router-link>
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
const displayName = ref("");
const loading = ref(false);
const error = ref("");
const success = ref("");

async function handleRegister() {
  loading.value = true;
  error.value = "";
  success.value = "";
  try {
    await store.register(email.value, password.value, displayName.value);
    success.value = "注册成功！即将跳转到登录页...";
    setTimeout(() => router.push("/login"), 1500);
  } catch (e: any) {
    error.value = e?.response?.data?.detail?.message || "注册失败，请重试";
  } finally {
    loading.value = false;
  }
}
</script>
