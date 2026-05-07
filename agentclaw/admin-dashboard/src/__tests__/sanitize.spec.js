import { describe, expect, it } from 'vitest'

import { highlightTextSafe, renderMarkdownSafe } from '../utils/sanitize'

describe('safe HTML rendering helpers', () => {
  it('sanitizes markdown before it is rendered with v-html', () => {
    const html = renderMarkdownSafe('<img src=x onerror="alert(1)">**ok**<script>alert(2)</script>')

    expect(html).not.toContain('onerror')
    expect(html).not.toContain('<script')
    expect(html).toContain('<strong>ok</strong>')
  })

  it('escapes knowledgebase preview text before adding highlights', () => {
    const html = highlightTextSafe('<img src=x onerror="alert(1)"> alpha', ['alpha'])
    const wrapper = document.createElement('div')
    wrapper.innerHTML = html

    expect(wrapper.querySelector('img')).toBe(null)
    expect(wrapper.querySelector('script')).toBe(null)
    expect(wrapper.textContent).toContain('onerror="alert(1)"')
    expect(html).toContain('&lt;img')
    expect(html).toContain('<mark')
    expect(html).toContain('alpha</mark>')
  })
})
