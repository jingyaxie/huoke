import { createRouter, createWebHistory } from "vue-router";
import HotVideoView from "../views/HotVideoView.vue";
import HotAuthorView from "../views/HotAuthorView.vue";
import TrendView from "../views/TrendView.vue";
import ReportView from "../views/ReportView.vue";
import CommentCrawlView from "../views/CommentCrawlView.vue";

const routes = [
  { path: "/", redirect: "/videos" },
  { path: "/videos", name: "videos", component: HotVideoView },
  { path: "/authors", name: "authors", component: HotAuthorView },
  { path: "/trend", name: "trend", component: TrendView },
  { path: "/reports", name: "reports", component: ReportView },
  { path: "/comments", name: "comments", component: CommentCrawlView },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
