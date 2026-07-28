import { defineStore } from "pinia";
import { ref } from "vue";
import { cloudApi } from "../api/cloud-auth";

// 客户端解析 JWT payload（仅读 account_type / roles 用于路由，不依赖服务端）
function decodeJwt(token: string): any {
  try {
    const payload = token.split(".")[1];
    const b64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(b64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("access_token"));
  const user = ref<any>(null);
  const accountType = ref<string | null>(localStorage.getItem("account_type"));
  const roles = ref<string[]>(JSON.parse(localStorage.getItem("roles") || "[]"));

  async function login(email: string, password: string) {
    const res = await cloudApi.unifiedLogin(email, password);
    const data = res.data.data;
    localStorage.setItem("access_token", data.access_token);
    if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
    token.value = data.access_token;

    // 从 JWT 解析 account_type / roles 供前端自动路由
    const claims = decodeJwt(data.access_token) || {};
    accountType.value = claims.account_type || res.data.account_type || "tenant";
    roles.value = claims.roles || [];
    localStorage.setItem("account_type", accountType.value as string);
    localStorage.setItem("roles", JSON.stringify(roles.value));
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

  function isSuperAdmin() {
    return accountType.value === "platform" && roles.value.includes("super_admin");
  }

  function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("account_type");
    localStorage.removeItem("roles");
    token.value = null;
    user.value = null;
    accountType.value = null;
    roles.value = [];
  }

  return { token, user, accountType, roles, login, register, fetchMe, isSuperAdmin, logout };
});
