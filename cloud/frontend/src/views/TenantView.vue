<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold text-gray-800">知微云 · 租户自助中心</h1>
        <p class="text-sm text-gray-500">
          当前账号：{{ auth.user?.email || '—' }}
          <span class="ml-2 px-2 py-0.5 rounded bg-green-100 text-green-700 text-xs">租户管理</span>
        </p>
      </div>
      <button @click="doLogout" class="text-sm text-gray-500 hover:text-gray-800">退出登录</button>
    </header>

    <main class="max-w-4xl mx-auto px-6 py-12">
      <div class="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-500">
        <p class="text-base">租户自助中心（License 激活 / 账单 / 发票）建设中。</p>
        <p class="text-sm mt-2">租户管理账号已可通过 cloud 统一登录进入；自助功能将在下一迭代开放。</p>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();

function doLogout() {
  auth.logout();
  router.push("/login");
}
</script>
