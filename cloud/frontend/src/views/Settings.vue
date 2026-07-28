<template>
  <div class="max-w-md mx-auto bg-white rounded-xl border border-gray-200 p-6">
    <h2 class="text-base font-semibold text-gray-800 mb-4">修改密码</h2>

    <div v-if="msg" class="bg-green-50 text-green-700 text-sm px-4 py-2 rounded-lg mb-3">{{ msg }}</div>
    <div v-if="err" class="bg-red-50 text-red-600 text-sm px-4 py-2 rounded-lg mb-3">{{ err }}</div>

    <form @submit.prevent="submit" class="space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">原密码</label>
        <input
          v-model="form.old_password"
          type="password"
          required
          autocomplete="current-password"
          class="w-full px-3 py-2.5 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">新密码</label>
        <input
          v-model="form.new_password"
          type="password"
          required
          minlength="6"
          autocomplete="new-password"
          class="w-full px-3 py-2.5 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">确认新密码</label>
        <input
          v-model="form.confirm"
          type="password"
          required
          minlength="6"
          autocomplete="new-password"
          class="w-full px-3 py-2.5 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <button
        type="submit"
        :disabled="saving"
        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-lg disabled:opacity-50"
      >
        {{ saving ? '提交中…' : '确认修改' }}
      </button>
    </form>
    <p class="text-xs text-gray-400 mt-3">修改成功后，当前账号在所有设备的登录状态将失效，需重新登录。</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { cloudApi, extractError } from "../api/cloud-auth";

const router = useRouter();
const auth = useAuthStore();

const form = ref({ old_password: "", new_password: "", confirm: "" });
const saving = ref(false);
const msg = ref("");
const err = ref("");

async function submit() {
  saving.value = true;
  msg.value = "";
  err.value = "";
  if (form.value.new_password !== form.value.confirm) {
    err.value = "两次输入的新密码不一致";
    saving.value = false;
    return;
  }
  try {
    await cloudApi.changePassword(form.value.old_password, form.value.new_password);
    msg.value = "密码已修改，正在退出登录…";
    setTimeout(() => {
      auth.logout();
      router.push("/login");
    }, 1200);
  } catch (e: any) {
    err.value = extractError(e);
  } finally {
    saving.value = false;
  }
}
</script>
