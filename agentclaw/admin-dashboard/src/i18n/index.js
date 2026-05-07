import { createI18n } from 'vue-i18n'
import zhCN from '../locales/zh-CN'
import enUS from '../locales/en-US'

export const DEFAULT_LOCALE_KEY = 'agentclaw.admin.locale'
export const SUPPORTED_LOCALES = ['zh-CN', 'en-US']

export const LOCALE_OPTIONS = [
  { label: '中文', value: 'zh-CN' },
  { label: 'English', value: 'en-US' },
]

const NAMED_PLACEHOLDER_RE = /\{([A-Za-z_$][\w$]*)\}/g

function interpolateNamedParams(template, getParam) {
  return template.replace(NAMED_PLACEHOLDER_RE, (match, key) => {
    const value = getParam(key)
    return value == null ? '' : String(value)
  })
}

function normalizeMessageCatalog(catalog) {
  if (typeof catalog === 'string') {
    return (ctx) => interpolateNamedParams(catalog, (key) => ctx.named?.(key))
  }
  if (Array.isArray(catalog)) {
    return catalog.map(normalizeMessageCatalog)
  }
  if (catalog && typeof catalog === 'object') {
    return Object.fromEntries(
      Object.entries(catalog).map(([key, value]) => [key, normalizeMessageCatalog(value)])
    )
  }
  return catalog
}

export function getStoredLocale() {
  if (typeof localStorage === 'undefined') return ''
  return localStorage.getItem(DEFAULT_LOCALE_KEY) || ''
}

export function getCurrentLocale() {
  return SUPPORTED_LOCALES.includes(getStoredLocale()) ? getStoredLocale() : resolveInitialLocale()
}

export function resolveInitialLocale() {
  const saved = getStoredLocale()
  if (SUPPORTED_LOCALES.includes(saved)) return saved
  const language = typeof navigator !== 'undefined' ? String(navigator.language || '').toLowerCase() : ''
  return language.startsWith('en') ? 'en-US' : 'zh-CN'
}

export function createAppI18n() {
  return createI18n({
    legacy: false,
    globalInjection: true,
    locale: resolveInitialLocale(),
    fallbackLocale: 'zh-CN',
    messages: {
      'zh-CN': normalizeMessageCatalog(zhCN),
      'en-US': normalizeMessageCatalog(enUS),
    },
  })
}

export function setLocale(i18n, locale) {
  const nextLocale = SUPPORTED_LOCALES.includes(locale) ? locale : 'zh-CN'
  const composer = i18n?.global?.locale ? i18n.global : i18n
  if (composer?.locale?.value == null) {
    throw new Error('Invalid i18n instance passed to setLocale')
  }
  composer.locale.value = nextLocale
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(DEFAULT_LOCALE_KEY, nextLocale)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = nextLocale
  }
}
