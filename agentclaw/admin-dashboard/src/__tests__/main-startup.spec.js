import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('dashboard startup', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('waits for the initial router navigation before mounting the app', async () => {
    let resolveRouterReady
    const routerReady = new Promise((resolve) => {
      resolveRouterReady = resolve
    })
    const router = {
      isReady: vi.fn(() => routerReady),
    }
    const app = {
      use: vi.fn(),
      mount: vi.fn(),
    }

    vi.doMock('vue', () => ({
      createApp: vi.fn(() => app),
    }))
    vi.doMock('pinia', () => ({
      createPinia: vi.fn(() => ({})),
    }))
    vi.doMock('../router', () => ({
      default: router,
    }))
    vi.doMock('../App.vue', () => ({
      default: {},
    }))
    vi.doMock('../i18n', () => ({
      createAppI18n: vi.fn(() => ({})),
    }))
    vi.doMock('../utils/canonicalHost', () => ({
      redirectInvalidBindHost: vi.fn(() => false),
    }))

    await import('../main.js')

    expect(router.isReady).toHaveBeenCalledTimes(1)
    expect(app.mount).not.toHaveBeenCalled()

    resolveRouterReady()
    await routerReady
    await Promise.resolve()

    expect(app.mount).toHaveBeenCalledWith('#app')
  })
})
