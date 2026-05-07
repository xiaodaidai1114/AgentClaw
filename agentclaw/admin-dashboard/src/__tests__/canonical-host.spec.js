import { describe, expect, it, vi } from 'vitest'

import { getCanonicalDashboardUrl, redirectInvalidBindHost } from '../utils/canonicalHost'

describe('canonical dashboard host', () => {
  it('rewrites browser visits to 0.0.0.0 onto 127.0.0.1 while preserving the URL', () => {
    const url = getCanonicalDashboardUrl({
      protocol: 'http:',
      hostname: '0.0.0.0',
      port: '8000',
      pathname: '/dashboard/agent/__builtin__',
      search: '?conversation_id=conv-1',
      hash: '#section',
    })

    expect(url).toBe('http://127.0.0.1:8000/dashboard/agent/__builtin__?conversation_id=conv-1#section')
  })

  it('does not rewrite normal localhost visits', () => {
    const url = getCanonicalDashboardUrl({
      protocol: 'http:',
      hostname: '127.0.0.1',
      port: '8000',
      pathname: '/dashboard',
      search: '',
      hash: '',
    })

    expect(url).toBe('')
  })

  it('uses location.replace for invalid bind host visits', () => {
    const replace = vi.fn()

    redirectInvalidBindHost({
      protocol: 'http:',
      hostname: '0.0.0.0',
      port: '6010',
      pathname: '/dashboard',
      search: '',
      hash: '',
      replace,
    })

    expect(replace).toHaveBeenCalledWith('http://127.0.0.1:6010/dashboard')
  })
})
