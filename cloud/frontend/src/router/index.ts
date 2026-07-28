import { createRouter, createWebHistory } from "vue-router";
import LoginView from "../views/LoginView.vue";
import RegisterView from "../views/RegisterView.vue";
import AdminConsole from "../views/AdminConsole.vue";
import TenantView from "../views/TenantView.vue";

const routes = [
  { path: "/", redirect: "/login" },
  { path: "/login", name: "Login", component: LoginView },
  { path: "/register", name: "Register", component: RegisterView },
  { path: "/console", name: "Console", component: AdminConsole, meta: { requiresAuth: true, accountType: "platform" } },
  { path: "/tenant", name: "Tenant", component: TenantView, meta: { requiresAuth: true, accountType: "tenant" } },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem("access_token");
  const accountType = localStorage.getItem("account_type");

  if (!token && to.name !== "Login" && to.name !== "Register") {
    next({ name: "Login" });
    return;
  }
  if (token && (to.name === "Login" || to.name === "Register")) {
    next({ name: accountType === "platform" ? "Console" : "Tenant" });
    return;
  }
  // 账号类型与页面不匹配时，回到本类型首页
  if (to.meta?.accountType && to.meta.accountType !== accountType) {
    next({ name: accountType === "platform" ? "Console" : "Tenant" });
    return;
  }
  next();
});

export default router;
