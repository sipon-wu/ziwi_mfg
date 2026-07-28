<template>
  <div class="min-h-screen bg-gray-50 pb-20 md:pb-0">
    <!-- 顶栏 -->
    <header class="bg-white border-b border-gray-200 px-4 md:px-6 py-4 flex items-center justify-between sticky top-0 z-10">
      <div>
        <h1 class="text-lg font-semibold text-gray-800">知微云 · 平台管理控制台</h1>
        <p class="text-sm text-gray-500">
          当前账号：{{ auth.user?.email || '—' }}
          <span class="ml-2 px-2 py-0.5 rounded bg-blue-100 text-blue-700 text-xs">{{ auth.roles.join(' / ') || '—' }}</span>
        </p>
      </div>
      <button @click="doLogout" class="text-sm text-gray-500 hover:text-gray-800 hidden md:block">退出登录</button>
    </header>

    <!-- 桌面端顶部 Tab -->
    <nav class="hidden md:flex gap-1 px-6 border-b border-gray-200 bg-white">
      <button
        v-for="t in tabs"
        :key="t.key"
        @click="tab = t.key"
        :class="tab === t.key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'"
        class="px-4 py-3 text-sm font-medium border-b-2"
      >{{ t.label }}</button>
    </nav>

    <main class="max-w-4xl mx-auto px-4 md:px-6 py-6 space-y-6">
      <!-- 总览看板 -->
      <Dashboard v-if="tab === 'dashboard'" />

      <!-- 账号管理 -->
      <div v-else-if="tab === 'users'" class="space-y-8">
        <section v-if="auth.isSuperAdmin()" class="bg-white rounded-xl border border-gray-200 p-6">
          <h2 class="text-base font-semibold text-gray-800 mb-4">新建平台管理账号</h2>
          <div v-if="formError" class="bg-red-50 text-red-600 text-sm px-4 py-2 rounded-lg mb-3">{{ formError }}</div>
          <div v-if="formOk" class="bg-green-50 text-green-700 text-sm px-4 py-2 rounded-lg mb-3">{{ formOk }}</div>
          <form @submit.prevent="createUser" class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">邮箱</label>
              <input v-model="form.email" type="email" required class="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">显示名</label>
              <input v-model="form.display_name" type="text" required class="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
              <input v-model="form.password" type="password" required class="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">角色</label>
              <select v-model="form.role" class="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500">
                <option value="super_admin">超级管理员</option>
                <option value="operator">运营</option>
                <option value="sales">销售</option>
                <option value="finance">财务</option>
                <option value="devops">运维</option>
                <option value="implementation">实施</option>
              </select>
            </div>
            <div class="col-span-1 sm:col-span-2">
              <button type="submit" :disabled="creating" class="bg-blue-600 hover:bg-blue-700 text-white font-medium px-5 py-2 rounded-lg disabled:opacity-50">
                {{ creating ? '创建中...' : '创建账号' }}
              </button>
            </div>
          </form>
        </section>
        <section v-else class="bg-yellow-50 text-yellow-700 text-sm px-4 py-3 rounded-lg">
          仅超级管理员可分配平台账号。
        </section>

        <section class="bg-white rounded-xl border border-gray-200 p-6">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-base font-semibold text-gray-800">平台账号列表</h2>
            <button @click="loadUsers" class="text-sm text-blue-600 hover:underline">刷新</button>
          </div>
          <!-- 桌面：表格 -->
          <table class="w-full text-sm hidden sm:table">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-100">
                <th class="py-2">邮箱</th>
                <th class="py-2">显示名</th>
                <th class="py-2">角色</th>
                <th class="py-2">状态</th>
                <th class="py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in users" :key="u.id" class="border-b border-gray-50">
                <td class="py-2">{{ u.email }}</td>
                <td class="py-2">{{ u.display_name }}</td>
                <td class="py-2"><span class="px-2 py-0.5 rounded bg-gray-100 text-gray-600 text-xs">{{ ROLE_LABELS[u.role] || u.role }}</span></td>
                <td class="py-2"><span :class="u.is_active ? 'text-green-600' : 'text-gray-400'">{{ u.is_active ? '启用' : '停用' }}</span></td>
                <td class="py-2">
                  <button v-if="auth.isSuperAdmin()" @click="toggleActive(u)" :disabled="togglingId === u.id" class="text-sm text-blue-600 hover:underline disabled:opacity-50">
                    {{ u.is_active ? '停用' : '启用' }}
                  </button>
                </td>
              </tr>
              <tr v-if="!users.length">
                <td colspan="5" class="py-4 text-center text-gray-400">暂无账号</td>
              </tr>
            </tbody>
          </table>
          <!-- 移动：卡片列表 -->
          <ul class="sm:hidden divide-y divide-gray-100">
            <li v-for="u in users" :key="u.id" class="py-3 flex items-center justify-between">
              <div>
                <p class="text-sm text-gray-800">{{ u.display_name }}</p>
                <p class="text-xs text-gray-400">{{ u.email }}</p>
                <p class="text-xs mt-0.5">
                  <span class="px-2 py-0.5 rounded bg-gray-100 text-gray-600">{{ ROLE_LABELS[u.role] || u.role }}</span>
                  <span :class="u.is_active ? 'text-green-600 ml-2' : 'text-gray-400 ml-2'">{{ u.is_active ? '启用' : '停用' }}</span>
                </p>
              </div>
              <button v-if="auth.isSuperAdmin()" @click="toggleActive(u)" :disabled="togglingId === u.id" class="text-sm text-blue-600 hover:underline disabled:opacity-50 shrink-0 ml-2">
                {{ u.is_active ? '停用' : '启用' }}
              </button>
            </li>
            <li v-if="!users.length" class="py-4 text-center text-gray-400 text-sm">暂无账号</li>
          </ul>
        </section>
      </div>

      <!-- 设置 -->
      <Settings v-else-if="tab === 'settings'" />
    </main>

    <!-- 移动端底部 Tab -->
    <nav class="md:hidden fixed bottom-0 inset-x-0 bg-white border-t border-gray-200 grid grid-cols-3 z-20">
      <button
        v-for="t in tabs"
        :key="t.key"
        @click="tab = t.key"
        :class="tab === t.key ? 'text-blue-600' : 'text-gray-500'"
        class="py-3 text-sm font-medium flex flex-col items-center gap-0.5"
      >
        <span>{{ t.icon }}</span>
        <span>{{ t.label }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { cloudApi, extractError } from "../api/cloud-auth";
import Dashboard from "./Dashboard.vue";
import Settings from "./Settings.vue";

const router = useRouter();
const auth = useAuthStore();

const tabs = [
  { key: "dashboard", label: "总览", icon: "📊" },
  { key: "users", label: "账号", icon: "👥" },
  { key: "settings", label: "设置", icon: "⚙️" },
];
const tab = ref<"dashboard" | "users" | "settings">("dashboard");

const users = ref<any[]>([]);
const form = ref({ email: "", display_name: "", password: "", role: "operator" });
const formError = ref("");
const formOk = ref("");
const creating = ref(false);
const togglingId = ref("");

const ROLE_LABELS: Record<string, string> = {
  super_admin: "超级管理员",
  operator: "运营",
  sales: "销售",
  finance: "财务",
  devops: "运维",
  implementation: "实施",
};

async function loadUsers() {
  try {
    const res = await cloudApi.listPlatformUsers();
    users.value = (res.data?.data ?? res.data) || [];
  } catch (e: any) {
    formError.value = extractError(e);
  }
}

async function createUser() {
  creating.value = true;
  formError.value = "";
  formOk.value = "";
  try {
    await cloudApi.createPlatformUser({ ...form.value });
    formOk.value = `已创建账号 ${form.value.email}`;
    form.value = { email: "", display_name: "", password: "", role: "operator" };
    await loadUsers();
  } catch (e: any) {
    formError.value = extractError(e);
  } finally {
    creating.value = false;
  }
}

async function toggleActive(u: any) {
  togglingId.value = u.id;
  try {
    await cloudApi.updatePlatformUser(u.id, { is_active: !u.is_active });
    await loadUsers();
  } catch (e: any) {
    formError.value = extractError(e);
  } finally {
    togglingId.value = "";
  }
}

function doLogout() {
  auth.logout();
  router.push("/login");
}

onMounted(loadUsers);
</script>
