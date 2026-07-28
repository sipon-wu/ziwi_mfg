import axios from "axios";

const http = axios.create({
  baseURL: "/api/v1",
  timeout: 10000,
});

// 请求拦截：自动附带 Bearer token（平台 / 租户管理端点需鉴权）
http.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 统一错误解析：覆盖 FastAPI 全部 4xx 形态（字符串 / {message} / 422 数组）
export function extractError(e: any): string {
  const detail = e?.response?.data?.detail;
  if (!detail) return e?.message || "操作失败";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d: any) => {
        const field = Array.isArray(d?.loc) ? d.loc.slice(1).join(".") : "";
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .filter(Boolean);
    return msgs.length ? msgs.join("；") : "请求参数错误";
  }
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  return "操作失败";
}

// 响应拦截：把后端 4xx 规范化为 e.userMessage，所有页面统一消费
http.interceptors.response.use(
  (r) => r,
  (error) => {
    error.userMessage = extractError(error);
    return Promise.reject(error);
  }
);

export const cloudApi = {
  // 统一登录：自动识别平台 / 租户账号
  unifiedLogin(email: string, password: string) {
    return http.post("/auth/unified-login", { email, password });
  },

  login(email: string, password: string) {
    return http.post("/auth/login", { email, password });
  },

  register(email: string, password: string, display_name: string) {
    return http.post("/auth/register", { email, password, display_name });
  },

  refresh(refreshToken: string) {
    return http.post("/auth/refresh", { refresh_token: refreshToken });
  },

  getMe(token: string) {
    return http.get("/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
  },

  getPublicKey() {
    return http.get("/auth/public-key");
  },

  // ── 平台账号管理（需平台 JWT）──
  listPlatformUsers() {
    return http.get("/platform/users");
  },

  createPlatformUser(payload: {
    email: string;
    password: string;
    display_name: string;
    role: string;
    phone?: string;
  }) {
    return http.post("/platform/users", payload);
  },

  updatePlatformUser(id: string, payload: { is_active?: boolean; display_name?: string; role?: string }) {
    return http.patch(`/platform/users/${id}`, payload);
  },
};
