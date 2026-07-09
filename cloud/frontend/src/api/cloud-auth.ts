import axios from "axios";

const http = axios.create({
  baseURL: "/api/v1",
  timeout: 10000,
});

export const cloudApi = {
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
};
