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
};
