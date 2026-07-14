import { createRouter, createWebHistory } from 'vue-router'

const dashboardRoutes = [
  {
    path: '/',
    redirect: '/builtin',
  },
  {
    path: '/builtin',
    name: 'BuiltinAgent',
    component: () => import('../views/BuiltinAgent.vue'),
  },
  {
    path: '/agents',
    redirect: '/workflows',
  },
  {
    path: '/templates',
    name: 'TemplateLibrary',
    component: () => import('../views/TemplateLibrary.vue'),
  },
  {
    path: '/enterprise-tools',
    name: 'EnterpriseTools',
    component: () => import('../views/EnterpriseTools.vue'),
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
  },
  {
    path: '/workflows',
    name: 'Workflows',
    component: () => import('../views/Workflows.vue'),
  },
  {
    path: '/workflows/:id',
    name: 'WorkflowDetail',
    component: () => import('../views/WorkflowDetail.vue'),
  },
  {
    path: '/workflows/:id/config',
    name: 'WorkflowConfig',
    component: () => import('../views/WorkflowConfig.vue'),
  },
  {
    path: '/workflows/:id/debug',
    name: 'WorkflowDebug',
    component: () => import('../views/WorkflowDebug.vue'),
  },
  {
    path: '/workflows/:id/chat',
    name: 'AgentChat',
    component: () => import('../views/AgentChat.vue'),
  },
  {
    path: '/workflows/:id/prompts',
    redirect: (to) => `/workflows/${to.params.id}/config`,
  },
  {
    path: '/agent/:id',
    name: 'PublicAgent',
    component: () => import('../views/PublicAgent.vue'),
    meta: { public: true },
  },
  {
    path: '/scheduler',
    name: 'Scheduler',
    component: () => import('../views/Scheduler.vue'),
  },
  {
    path: '/scheduler/:id',
    name: 'SchedulerDetail',
    component: () => import('../views/SchedulerDetail.vue'),
  },
  {
    path: '/channels',
    name: 'Channels',
    component: () => import('../views/Channels.vue'),
  },
  {
    path: '/channels/logs',
    redirect: '/channels?tab=logs',
  },
  {
    path: '/public-rooms',
    name: 'PublicRooms',
    component: () => import('../views/PublicRooms.vue'),
  },
  {
    path: '/traces',
    redirect: '/dashboard?tab=traces',
  },
  {
    path: '/traces/:id',
    name: 'TraceDetail',
    component: () => import('../views/TraceDetail.vue'),
  },
  {
    path: '/prompts',
    redirect: '/workflows',
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
  },
  {
    path: '/knowledgebases',
    name: 'KnowledgeBases',
    component: () => import('../views/KnowledgeBases.vue'),
  },
  {
    path: '/knowledgebases/:id',
    name: 'KnowledgebaseDetail',
    component: () => import('../views/KnowledgebaseDetail.vue'),
  },
  {
    path: '/knowledgebases/:id/documents',
    name: 'KnowledgebaseDocuments',
    redirect: (to) => `/knowledgebases/${to.params.id}`,
  },
  {
    path: '/knowledgebases/:id/search',
    name: 'KnowledgebaseSearch',
    component: () => import('../views/KnowledgebaseSearch.vue'),
  },
  {
    path: '/knowledgebases/:id/documents/:documentId',
    name: 'KnowledgebaseDocumentDetail',
    component: () => import('../views/KnowledgebaseDocumentDetail.vue'),
  },
]

const squareRoutes = [
  {
    path: '/',
    name: 'PublicSquare',
    component: () => import('../views/PublicSquare.vue'),
    meta: { public: true },
  },
  {
    path: '/agent/:id',
    name: 'PublicAgent',
    component: () => import('../views/PublicAgent.vue'),
    meta: { public: true },
  },
]

const isSquareBase = window.location.pathname === '/square' || window.location.pathname.startsWith('/square/')
const routes = isSquareBase ? squareRoutes : dashboardRoutes

const router = createRouter({
  // 使用服务端入口作为路由基础路径（与 vite.config.js 的 base 配合）
  history: createWebHistory(isSquareBase ? '/square' : '/dashboard'),
  routes,
})

export default router
