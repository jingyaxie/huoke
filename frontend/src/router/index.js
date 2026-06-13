import { createRouter, createWebHistory } from "vue-router";
import AntibotView from "../views/AntibotView.vue";
import AgentChatView from "../views/AgentChatView.vue";
import LoginView from "../views/LoginView.vue";
import ExternalApiView from "../views/ExternalApiView.vue";
import TestHubView from "../views/TestHubView.vue";
import CrawlDataView from "../views/CrawlDataView.vue";
import CommentUserView from "../views/CommentUserView.vue";
import TaskListView from "../views/TaskListView.vue";
import TaskDetailView from "../views/TaskDetailView.vue";
import TaskCreateView from "../views/TaskCreateView.vue";
import TaskCompileView from "../views/TaskCompileView.vue";
import TaskLayout from "../layouts/TaskLayout.vue";
import OrchestrationLayout from "../layouts/OrchestrationLayout.vue";
import AgentOrchestrationView from "../views/AgentOrchestrationView.vue";

const routes = [
  { path: "/", redirect: "/test" },
  { path: "/test", name: "test", component: TestHubView },
  { path: "/crawl-data", name: "crawl-data", component: CrawlDataView },
  { path: "/crawl-data/user", name: "crawl-data-user", component: CommentUserView },
  {
    path: "/tasks",
    component: TaskLayout,
    children: [
      { path: "", name: "tasks", component: TaskListView },
      { path: "create", name: "task-create", component: TaskCreateView },
      { path: "compile", name: "task-compile", component: TaskCompileView },
      { path: ":taskId", name: "task-detail", component: TaskDetailView },
    ],
  },
  { path: "/external-api", name: "external-api", component: ExternalApiView },
  {
    path: "/orchestration",
    component: OrchestrationLayout,
    children: [{ path: "", name: "orchestration", component: AgentOrchestrationView }],
  },
  { path: "/login", name: "login", component: LoginView },
  { path: "/antibot", name: "antibot", component: AntibotView },
  { path: "/agent", name: "agent", component: AgentChatView },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
