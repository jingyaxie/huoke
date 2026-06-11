import { createRouter, createWebHistory } from "vue-router";
import HotVideoView from "../views/HotVideoView.vue";
import HotAuthorView from "../views/HotAuthorView.vue";
import TrendView from "../views/TrendView.vue";
import ReportView from "../views/ReportView.vue";
import CommentCrawlView from "../views/CommentCrawlView.vue";
import AntibotView from "../views/AntibotView.vue";
import AgentChatView from "../views/AgentChatView.vue";
import LoginView from "../views/LoginView.vue";
import ExternalApiView from "../views/ExternalApiView.vue";

const routes = [
  { path: "/", redirect: "/videos" },
  { path: "/videos", name: "videos", component: HotVideoView },
  { path: "/authors", name: "authors", component: HotAuthorView },
  { path: "/trend", name: "trend", component: TrendView },
  { path: "/reports", name: "reports", component: ReportView },
  { path: "/comments", name: "comments", component: CommentCrawlView },
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
