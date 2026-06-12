import { createRouter, createWebHistory } from "vue-router";
import AntibotView from "../views/AntibotView.vue";
import AgentChatView from "../views/AgentChatView.vue";
import LoginView from "../views/LoginView.vue";
import ExternalApiView from "../views/ExternalApiView.vue";
import TestHubView from "../views/TestHubView.vue";
import CrawlDataView from "../views/CrawlDataView.vue";
import CommentUserView from "../views/CommentUserView.vue";

const routes = [
  { path: "/", redirect: "/test" },
  { path: "/test", name: "test", component: TestHubView },
  { path: "/crawl-data", name: "crawl-data", component: CrawlDataView },
  { path: "/crawl-data/user", name: "crawl-data-user", component: CommentUserView },
  { path: "/external-api", name: "external-api", component: ExternalApiView },
  { path: "/login", name: "login", component: LoginView },
  { path: "/antibot", name: "antibot", component: AntibotView },
  { path: "/agent", name: "agent", component: AgentChatView },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
