<template>
  <div class="json-code-block" :class="[`tone-${tone}`]">
    <div class="json-code-toolbar">
      <div class="json-code-label">
        <span class="json-code-dot"></span>
        <span>{{ label }}</span>
      </div>
      <div class="json-code-actions">
        <button class="json-action-btn" :class="{ copied }" :title="copied ? $t('jsonCodeBlock.copied') : $t('jsonCodeBlock.copyJson')" @click="copyContent">
          <svg v-if="!copied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" />
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </button>
        <button class="json-action-btn" :title="$t('jsonCodeBlock.fullscreen')" @click="isFullscreen = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M8 3H5a2 2 0 00-2 2v3M16 3h3a2 2 0 012 2v3M8 21H5a2 2 0 01-2-2v-3M16 21h3a2 2 0 002-2v-3" />
          </svg>
        </button>
      </div>
    </div>

    <div class="json-code-body">
      <pre class="json-code-pre"><code class="hljs language-json" v-html="highlightedHtml"></code></pre>
    </div>

    <div v-if="isFullscreen" class="json-code-overlay" @click.self="isFullscreen = false">
      <div class="json-code-dialog">
        <div class="json-code-toolbar">
          <div class="json-code-label">
            <span class="json-code-dot"></span>
            <span>{{ label }}</span>
          </div>
          <div class="json-code-actions">
            <button class="json-action-btn" :class="{ copied }" :title="copied ? $t('jsonCodeBlock.copied') : $t('jsonCodeBlock.copyJson')" @click="copyContent">
              <svg v-if="!copied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" />
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 6L9 17l-5-5" />
              </svg>
            </button>
            <button class="json-action-btn" :title="$t('jsonCodeBlock.closeFullscreen')" @click="isFullscreen = false">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div class="json-code-dialog-body">
          <pre class="json-code-pre fullscreen"><code class="hljs language-json" v-html="highlightedHtml"></code></pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import hljs from 'highlight.js'

function escapeHtml(input) {
  return String(input || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export default {
  name: 'JsonCodeBlock',
  props: {
    label: { type: String, default: 'JSON' },
    value: { type: [Object, Array, String, Number, Boolean], default: null },
    tone: { type: String, default: 'default' },
  },
  data() {
    return {
      copied: false,
      copyTimer: null,
      isFullscreen: false,
    }
  },
  computed: {
    rawText() {
      if (typeof this.value === 'string') return this.value
      try {
        return JSON.stringify(this.value, null, 2)
      } catch {
        return String(this.value ?? '')
      }
    },
    highlightedHtml() {
      if (!this.rawText) return ''
      try {
        return hljs.highlight(this.rawText, { language: 'json' }).value
      } catch {
        return escapeHtml(this.rawText)
      }
    },
  },
  beforeUnmount() {
    if (this.copyTimer) clearTimeout(this.copyTimer)
  },
  methods: {
    async copyContent() {
      try {
        await navigator.clipboard.writeText(this.rawText)
        this.copied = true
        if (this.copyTimer) clearTimeout(this.copyTimer)
        this.copyTimer = setTimeout(() => {
          this.copied = false
          this.copyTimer = null
        }, 1400)
      } catch (error) {
        console.error('复制失败:', error)
      }
    },
  },
}
</script>

<style scoped>
.json-code-block {
  background: linear-gradient(180deg, rgba(250, 252, 255, 0.98), rgba(244, 247, 251, 0.98));
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 16px 28px -24px rgba(15, 23, 42, 0.22);
}

.json-code-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: linear-gradient(180deg, rgba(245, 248, 252, 0.96), rgba(237, 242, 247, 0.94));
  border-bottom: 1px solid rgba(203, 213, 225, 0.72);
}

.json-code-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.json-code-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #64748b;
  box-shadow: 0 0 0 4px rgba(100, 116, 139, 0.12);
}

.tone-error .json-code-label { color: #991b1b; }
.tone-error .json-code-dot {
  background: #f87171;
  box-shadow: 0 0 0 4px rgba(248, 113, 113, 0.12);
}

.json-code-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.json-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px;
  width: 30px;
  height: 30px;
  border: 1px solid rgba(203, 213, 225, 0.92);
  background: rgba(255, 255, 255, 0.92);
  color: #475569;
  border-radius: 999px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  transition: all 0.18s ease;
}

.json-action-btn:hover {
  color: #0f172a;
  border-color: rgba(148, 163, 184, 0.95);
  background: rgba(248, 250, 252, 0.98);
}

.json-action-btn.copied {
  color: #166534;
  border-color: rgba(134, 239, 172, 0.48);
  background: rgba(240, 253, 244, 0.96);
}

.json-action-btn svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.json-code-body {
  padding: 0;
}

.json-code-pre {
  margin: 0;
  padding: 10px 12px 12px;
  max-height: 300px;
  overflow: auto;
  color: #0f172a;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(247, 250, 252, 0.96));
}

.json-code-pre.fullscreen {
  max-height: min(78vh, 920px);
  font-size: 13px;
}

.json-code-pre code {
  display: block;
  min-width: max-content;
}

.json-code-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.28);
  backdrop-filter: blur(8px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}

.json-code-dialog {
  width: min(1100px, 96vw);
  max-height: 88vh;
  background: linear-gradient(180deg, rgba(250, 252, 255, 0.99), rgba(244, 247, 251, 1));
  border: 1px solid rgba(203, 213, 225, 0.92);
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 30px 90px -40px rgba(15, 23, 42, 0.42);
}

.json-code-dialog-body {
  overflow: auto;
}

.json-code-pre :deep(.hljs) { background: transparent; color: #0f172a; }
.json-code-pre :deep(.hljs-attr) { color: #334155; font-weight: 600; }
.json-code-pre :deep(.hljs-string) { color: #0f766e; }
.json-code-pre :deep(.hljs-number) { color: #7c3aed; }
.json-code-pre :deep(.hljs-literal),
.json-code-pre :deep(.hljs-keyword) { color: #b45309; }
.json-code-pre :deep(.hljs-punctuation) { color: #94a3b8; }
.json-code-pre :deep(.hljs-comment) { color: #94a3b8; font-style: italic; }

@media (max-width: 768px) {
  .json-code-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .json-code-actions {
    width: 100%;
    justify-content: flex-end;
    flex-wrap: wrap;
  }

  .json-code-overlay {
    padding: 16px;
  }
}
</style>
