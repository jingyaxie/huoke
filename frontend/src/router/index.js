import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "../components/MainLayout.vue";
import AutoTasksView from "../views/acquisition/AutoTasksView.vue";
import ManualTasksView from "../views/acquisition/ManualTasksView.vue";
import AccountSettingsView from "../views/acquisition/AccountSettingsView.vue";
import LlmSettingsView from "../views/acquisition/LlmSettingsView.vue";
import PresetsView from "../views/acquisition/PresetsView.vue";
import AntibotView from "../views/AntibotView.vue";
import AgentChatView from "../views/AgentChatView.vue";
import LoginView from "../views/LoginView.vue";
import ExternalApiView from "../views/ExternalApiView.vue";
import CrawlDataView from "../views/CrawlDataView.vue";
import CommentUserView from "../views/CommentUserView.vue";
import TaskListView from "../views/TaskListView.vue";
import AgentJobDetailView from "../views/AgentJobDetailView.vue";
import TaskLayout from "../layouts/TaskLayout.vue";
import SettingsView from "../views/SettingsView.vue";
import SettingsGeneralSection from "../views/settings/SettingsGeneralSection.vue";
import SettingsAccountSection from "../views/settings/SettingsAccountSection.vue";
import SettingsRuntimeSection from "../views/settings/SettingsRuntimeSection.vue";
import SettingsSkillsSection from "../views/settings/SettingsSkillsSection.vue";
import SettingsRulesSection from "../views/settings/SettingsRulesSection.vue";
import SettingsExperiencesSection from "../views/settings/SettingsExperiencesSection.vue";
import SettingsAgentsSection from "../views/settings/SettingsAgentsSection.vue";
import SettingsModelSection from "../views/settings/SettingsModelSection.vue";

const routes = [
  {
    path: "/",
    component: MainLayout,
    children: [
      { path: "", redirect: "/auto-tasks" },
      { path: "auto-tasks", name: "auto-tasks", component: AutoTasksView },
      { path: "manual-tasks", name: "manual-tasks", component: ManualTasksView },
      { path: "account-settings", name: "account-settings", component: AccountSettingsView },
      { path: "llm-settings", name: "llm-settings", component: LlmSettingsView },
      { path: "presets", name: "presets", component: PresetsView },
      {
        path: "agent",
        name: "agent",
        component: AgentChatView,
        meta: { layoutMode: "full" },
      },
      { path: "crawl-data", name: "crawl-data", component: CrawlDataView },
      { path: "crawl-data/user", name: "crawl-data-user", component: CommentUserView },
      {
        path: "tasks",
        component: TaskLayout,
        children: [
          { path: "", name: "tasks", component: TaskListView },
          { path: "jobs/:jobId", name: "agent-job-detail", component: AgentJobDetailView },
        ],
      },
      { path: "external-api", name: "external-api", component: ExternalApiView },
      { path: "orchestration", redirect: "/tasks" },
      { path: "tasks/create", redirect: "/tasks" },
      { path: "tasks/compile", redirect: "/tasks" },
      {
        path: "settings",
        component: SettingsView,
        redirect: "/settings/general",
        children: [
          { path: "general", name: "settings-general", component: SettingsGeneralSection },
          { path: "model", name: "settings-model", component: SettingsModelSection },
          { path: "account", name: "settings-account", component: SettingsAccountSection },
          { path: "runtime", name: "settings-runtime", component: SettingsRuntimeSection },
          { path: "skills", name: "settings-skills", component: SettingsSkillsSection },
          { path: "rules", name: "settings-rules", component: SettingsRulesSection },
          { path: "experiences", name: "settings-experiences", component: SettingsExperiencesSection },
          { path: "agents", name: "settings-agents", component: SettingsAgentsSection },
        ],
      },
      { path: "login", redirect: "/account-settings" },
      { path: "antibot", name: "antibot", component: AntibotView },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
