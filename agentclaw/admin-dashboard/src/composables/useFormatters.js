/**
 * 通用格式化工具（纯函数导出）
 */
import { getCurrentLocale } from '../i18n'

export function formatDateTime(val, locale = getCurrentLocale()) {
  if (!val) return '-'
  return new Date(val).toLocaleString(locale)
}

export function formatDate(val, locale = getCurrentLocale()) {
  if (!val) return '-'
  return new Date(val).toLocaleDateString(locale)
}

export function formatTime(val, locale = getCurrentLocale(), options = {}) {
  if (!val) return '-'
  return new Date(val).toLocaleTimeString(locale, options)
}

export function formatDuration(ms) {
  if (ms == null) return '-'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms.toFixed(0)}ms`
}

export function durationBarPercent(ms, durations = []) {
  const value = Number(ms)
  if (!Number.isFinite(value) || value <= 0) return 0

  const positiveDurations = durations
    .map((duration) => Number(duration))
    .filter((duration) => Number.isFinite(duration) && duration > 0)
  const values = positiveDurations.includes(value) ? positiveDurations : [...positiveDurations, value]
  const max = Math.max(...values, 1)
  if (max <= 0) return 0

  const sorted = [...values].sort((a, b) => a - b)
  const median = sorted[Math.floor((sorted.length - 1) / 2)] || 1
  const heavilySkewed = max / median >= 20
  const percent = heavilySkewed
    ? (Math.log1p(value) / Math.log1p(max)) * 100
    : (value / max) * 100

  return Math.min(100, Math.max(0, percent))
}

export function formatTokens(val) {
  const num = Number(val || 0)
  const abs = Math.abs(num)

  if (abs >= 1_000_000_000) return formatCompact(num, 1_000_000_000, 'B')
  if (abs >= 1_000_000) return formatCompact(num, 1_000_000, 'M')
  if (abs >= 1_000) return formatCompact(num, 1_000, 'K')
  return String(Math.round(num))
}

function formatCompact(num, divisor, suffix) {
  const value = num / divisor
  return `${value.toFixed(1).replace(/\.0$/, '')}${suffix}`
}

export function formatNumber(val, locale = getCurrentLocale()) {
  if (val == null) return '-'
  return Number(val).toLocaleString(locale)
}
