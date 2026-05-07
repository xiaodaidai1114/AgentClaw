import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import { marked } from 'marked'

marked.setOptions({
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch {
        return ''
      }
    }
    return hljs.highlightAuto(code).value
  },
  breaks: true,
  gfm: true,
  tables: true,
})

const HTML_ENTITIES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => HTML_ENTITIES[char])
}

export function sanitizeHtml(html) {
  return DOMPurify.sanitize(String(html ?? ''), {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel'],
    FORBID_ATTR: ['style'],
  })
}

export function renderMarkdownSafe(markdown) {
  try {
    return sanitizeHtml(marked.parse(String(markdown ?? '')))
  } catch {
    return escapeHtml(markdown)
  }
}

export function highlightTextSafe(text, terms = []) {
  const escapedText = escapeHtml(text)
  const escapedTerms = terms
    .map((term) => escapeHtml(String(term ?? '').trim()))
    .filter(Boolean)
    .map(escapeRegex)

  if (!escapedTerms.length) return escapedText

  const pattern = new RegExp(`(${escapedTerms.join('|')})`, 'gi')
  const highlighted = escapedText.replace(
    pattern,
    '<mark class="kb-search-highlight">$1</mark>'
  )

  return sanitizeHtml(highlighted)
}
