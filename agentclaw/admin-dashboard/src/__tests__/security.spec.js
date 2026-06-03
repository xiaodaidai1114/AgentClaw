import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('dashboard security posture', () => {
  it('exposes /agent/:id as an anonymous public route without the admin shell', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')
    const routerSource = readFileSync(resolve(process.cwd(), 'src/router/index.js'), 'utf8')

    expect(appSource).not.toContain('route.query.public')
    expect(routerSource).toContain("path: '/agent/:id'")
    expect(routerSource).toContain("component: () => import('../views/PublicAgent.vue')")
    expect(routerSource).toContain("meta: { public: true }")
    expect(appSource).toContain("LoginModal v-if=\"!isPublicRoute\"")
  })

  it('does not mount protected dashboard routes before an admin token is present', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')

    expect(appSource).toContain('getAdminToken')
    expect(appSource).toContain('hasAuthenticatedAdmin')
    expect(appSource).toContain('admin-auth-updated')
    expect(appSource).toContain('<router-view v-if="isPublicRoute || hasAuthenticatedAdmin"')
    expect(appSource).toContain("window.addEventListener('admin-auth-required'")
  })

  it('copies the anonymous public agent URL for sharing', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/WorkflowDetail.vue'), 'utf8')
    const chatSource = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')
    const configSource = readFileSync(resolve(process.cwd(), 'src/views/WorkflowConfig.vue'), 'utf8')

    expect(source).toContain('copyChatLink')
    expect(source).toContain('isBuiltinWorkflow')
    expect(source).toContain('v-if="!isBuiltinWorkflow"')
    expect(source).toContain("router.resolve({ name: 'PublicAgent'")
    expect(source).toContain("params: { id: workflowId.value }")
    expect(source).toContain("query: { share_token: publicShareToken.value }")
    expect(source).toContain("workflowDetail.publicShareDisabled")
    expect(source).toContain("message.warning(t('workflowDetail.builtinShareDisabled'))")
    expect(source).not.toContain('`/workflows/${workflowId.value}/chat`')
    expect(chatSource).not.toContain("this.$route.query.public === '1'")
    expect(configSource).toContain('workflowForm.public_share_enabled')
    expect(configSource).toContain('workflowForm.workflow_api_key')
    expect(configSource).toContain('workflowForm.inject_as_agentic_capability')
    expect(configSource).toContain('workflowConfig.workflow.injectAsAgenticCapability')
    expect(configSource).toContain(':disabled="isBuiltinWorkflow"')
    expect(configSource).toContain("workflowConfig.workflow.builtinPublicShareDisabled")
  })

  it('removes the public share token from the URL and sends it in headers', () => {
    const pageSource = readFileSync(resolve(process.cwd(), 'src/views/PublicAgent.vue'), 'utf8')
    const chatSource = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')

    expect(pageSource).toContain(':share-token="shareToken"')
    expect(pageSource).toContain("route.query.share_token || route.query.token")
    expect(pageSource).toContain('shareTokenStorageKey')
    expect(pageSource).toContain('sessionStorage.setItem(shareTokenStorageKey')
    expect(pageSource).toContain('sessionStorage.getItem(shareTokenStorageKey')
    expect(pageSource).toContain('router.replace')
    expect(pageSource).toContain('shareTokenRef')
    expect(pageSource).toContain('delete query.share_token')
    expect(pageSource).toContain('delete query.token')
    expect(chatSource).toContain('shareToken: { type: String, default: \'\'}')
    expect(chatSource).toContain('publicWorkflowsApi.get(this.currentWorkflowId, this.shareToken)')
    expect(chatSource).toContain('publicWorkflowsApi.openSession(this.currentWorkflowId, this.shareToken)')
    expect(chatSource).toContain("headers['X-AgentClaw-Share-Token'] = this.shareToken")
    expect(chatSource).not.toContain('endpoint += `?share_token=')
    expect(chatSource).not.toContain('body.share_token = this.shareToken')
    expect(chatSource).toContain('this.convApi.create(this.currentWorkflowId, null, source, this.shareToken)')
    expect(apiSource).toContain('publicShareHeaders')
    expect(apiSource).not.toContain('publicShareTokenParams')
    expect(apiSource).not.toContain('params: publicShareTokenParams')
    expect(apiSource).not.toContain('share_token: shareToken')
    expect(apiSource).toContain('const headers = { ...publicSessionHeaders')
    expect(apiSource).toContain("headers['X-AgentClaw-Share-Token'] = shareToken")
    expect(apiSource).toContain('/public/workflows/')
  })

  it('requires a webhook secret in the scheduler job form when webhook is enabled', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/scheduler/JobFormModal.vue'), 'utf8')
    const zh = readFileSync(resolve(process.cwd(), 'src/locales/zh-CN.js'), 'utf8')
    const en = readFileSync(resolve(process.cwd(), 'src/locales/en-US.js'), 'utf8')

    expect(source).toContain('schedulerJobForm.webhook.secretRequired')
    expect(source).toContain('form.webhook.secret.trim()')
    expect(zh).toContain('secretRequired')
    expect(en).toContain('secretRequired')
  })

  it('streams workflow debug events with Authorization headers instead of query tokens', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/WorkflowDebug.vue'), 'utf8')

    expect(source).toContain('fetch(url')
    expect(source).toContain('Authorization: `Bearer ${token}`')
    expect(source).toContain("response.status === 401")
    expect(source).toContain("window.dispatchEvent(new CustomEvent('admin-auth-required'))")
    expect(source).not.toContain('/stream?token=')
    expect(source).not.toContain('new EventSource')
  })

  it('does not initialize secret settings fields from raw secret values', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')

    expect(source).not.toContain("if (variable.secret) return variable.raw_value ?? ''")
    expect(source).toContain("if (variable.secret) return variable.value ?? ''")
  })

  it('does not advertise legacy anonymous agent routes from the backend mount', () => {
    const source = readFileSync(resolve(process.cwd(), '../api/server.py'), 'utf8')

    expect(source).not.toContain('公开访问的智能体页面')
    expect(source).not.toContain('无需登录')
    expect(source).not.toContain('?public=1')
  })
})
