import { createRouter, createWebHistory } from "vue-router";
import LoginView from "../views/LoginView.vue";
import RegisterView from "../views/RegisterView.vue";

const routes = [
  { path: "/", redirect: "/login" },
  { path: "/login", name: "Login", component: LoginView },
  { path: "/register", name: "Register", component: RegisterView },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((_to, _from, next) => {
  const token = localStorage.getItem("access_token");
  if (!token && _to.name && _to.name !== "Login" && _to.name !== "Register") {
    next({ name: "Login" });
  } else {
    next();
  }
});

export default router;
