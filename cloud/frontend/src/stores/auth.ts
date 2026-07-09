import { defineStore } from "pinia";
import { ref } from "vue";
import { cloudApi } from "../api/cloud-auth";

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("access_token"));
  const user = ref<any>(null);

  async function login(email: string, password: string) {
    const res = await cloudApi.login(email, password);
    const data = res.data.data;
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    token.value = data.access_token;
    return data;
  }

  async function register(email: string, password: string, displayName: string) {
    const res = await cloudApi.register(email, password, displayName);
    return res.data.data;
  }

  async function fetchMe() {
    if (!token.value) throw new Error("Not authenticated");
    const res = await cloudApi.getMe(token.value);
    user.value = res.data.data;
    return user.value;
  }

  function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    token.value = null;
    user.value = null;
  }

  return { token, user, login, register, fetchMe, logout };
});
