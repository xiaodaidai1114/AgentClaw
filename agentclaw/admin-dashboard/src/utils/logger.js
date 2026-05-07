/**
 * 前端日志工具
 *
 * 使用方式：
 * import { logger } from '@/utils/logger'
 * logger.debug('debug message')
 * logger.info('info message')
 * logger.api('GET', '/api/workflows', params, response)
 * logger.event('message_end', eventData)
 */

const LOG_LEVEL = import.meta.env.VITE_LOG_LEVEL || 'debug'

const levels = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
  none: 4
}

const currentLevel = levels[LOG_LEVEL] || levels.debug

export const logger = {
  debug(...args) {
    if (currentLevel <= levels.debug) {
      console.log('[DEBUG]', ...args)
    }
  },

  info(...args) {
    if (currentLevel <= levels.info) {
      console.log('[INFO]', ...args)
    }
  },

  warn(...args) {
    if (currentLevel <= levels.warn) {
      console.warn('[WARN]', ...args)
    }
  },

  error(...args) {
    if (currentLevel <= levels.error) {
      console.error('[ERROR]', ...args)
    }
  },

  /**
   * API 调用日志
   * @param {string} method - HTTP 方法
   * @param {string} url - 请求 URL
   * @param {any} params - 请求参数
   * @param {any} response - 响应数据
   */
  api(method, url, params, response) {
    if (currentLevel <= levels.debug) {
      console.group(`[API] ${method} ${url}`)
      if (params) console.log('Params:', params)
      if (response) console.log('Response:', response)
      console.groupEnd()
    }
  },

  /**
   * SSE 事件日志
   * @param {string} eventType - 事件类型
   * @param {any} eventData - 事件数据
   */
  event(eventType, eventData) {
    if (currentLevel <= levels.debug) {
      console.group(`[EVENT] ${eventType}`)
      console.log('Data:', eventData)
      console.groupEnd()
    }
  }
}
