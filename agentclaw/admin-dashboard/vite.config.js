import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// 从环境变量读取 API 端口，默认 8000
const apiPort = process.env.VITE_API_PORT || '8000'
const dirname = fileURLToPath(new URL('.', import.meta.url))
const appVersion = readFileSync(resolve(dirname, '../../VERSION'), 'utf8').trim() || '1.0.0'

export default defineConfig({
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  // 生产构建时使用 /dashboard/ 作为基础路径
  base: '/dashboard/',
  server: {
    port: 3000,
    proxy: {
      '/admin': {
        target: `http://localhost:${apiPort}`,
        changeOrigin: true,
      },
      '/api': {
        target: `http://localhost:${apiPort}`,
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          'highlight': ['highlight.js'],
          'marked': ['marked'],
        },
      },
    },
  },
})
