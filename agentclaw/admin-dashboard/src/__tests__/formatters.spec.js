import { describe, expect, it } from 'vitest'
import { durationBarPercent, formatDateTime } from '../composables/useFormatters'

describe('formatters', () => {
  it('formats dates with the requested locale', () => {
    const value = '2026-04-22T12:34:56Z'
    const zh = formatDateTime(value, 'zh-CN')
    const en = formatDateTime(value, 'en-US')
    expect(zh).not.toBe(en)
    expect(typeof zh).toBe('string')
    expect(typeof en).toBe('string')
  })

  it('keeps duration bars readable when a single outlier is huge', () => {
    const durations = [1_000, 2_000, 3_000, 50_000_000]

    expect(durationBarPercent(1_000, durations)).toBeGreaterThan(20)
    expect(durationBarPercent(50_000_000, durations)).toBe(100)
  })

  it('keeps duration bars linear when durations are not heavily skewed', () => {
    expect(durationBarPercent(50, [25, 50, 100])).toBeCloseTo(50)
    expect(durationBarPercent(null, [25, 50, 100])).toBe(0)
  })
})
