<template>
  <div class="input-area" @dragover.prevent="onDragOver" @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
    <div class="drop-overlay" v-if="isDragging">
      <div class="drop-overlay-content">{{ $t('chatInput.dropToUpload') }}</div>
    </div>
    <div class="input-wrapper">
      <div class="input-container" :class="{ focused: inputFocused }">
        <!-- 错误提示 -->
        <div v-if="inputError" class="input-error">{{ inputError }}</div>
        <!-- 附件 -->
        <div v-if="attachedFiles.length" class="attached-files">
          <div v-for="(file, i) in attachedFiles" :key="i" class="file-chip">
            <span class="file-name">{{ file.original_name }}</span>
            <button class="file-remove" @click="$emit('remove-file', i)">&#10005;</button>
          </div>
        </div>
        <textarea
          ref="textarea"
          class="input-textarea"
          :placeholder="resolvedPlaceholder"
          :disabled="!enabled"
          v-model="text"
          @input="autoResize"
          @keydown.enter="onEnter"
          @focus="inputFocused = true"
          @blur="inputFocused = false"
          rows="1"
        ></textarea>
        <div class="input-toolbar">
          <div class="toolbar-left">
            <button v-if="uploadAvailable" class="toolbar-icon-btn" :title="$t('chatInput.addAttachment')" @click="$emit('attach')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
            </button>
            <button class="toolbar-icon-btn danger-hover" :title="$t('chatInput.clearConversation')" @click="$emit('clear')">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            </button>
          </div>
          <div class="toolbar-right">
            <button class="context-meter" type="button" :disabled="!canCompressContext" :title="contextMeterTitle" @click="$emit('compress-context')">
              <div class="context-meter-head">
                <span class="context-label">{{ $t('chatInput.context') }}</span>
                <strong class="context-value mono-font">{{ contextSummary }}</strong>
              </div>
              <div class="context-bar" aria-hidden="true">
                <span class="context-bar-fill" :class="usageTone" :style="{ width: `${usagePercent}%` }"></span>
              </div>
            </button>
            <button
              class="btn-send"
              :class="{ streaming: isStreaming, ready: !isStreaming && canSend }"
              :disabled="isStreaming ? false : !canSend"
              @click="$emit('send')"
            >
              <svg v-if="isStreaming" width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="4" y="4" width="8" height="8" rx="1"/></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ChatInput',
  props: {
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: '' },
    enabled: { type: Boolean, default: true },
    isStreaming: { type: Boolean, default: false },
    contextDisplay: { type: String, default: '0' },
    contextUsed: { type: Number, default: 0 },
    contextLimit: { type: Number, default: 128000 },
    uploadAvailable: { type: Boolean, default: false },
    attachedFiles: { type: Array, default: () => [] },
    inputError: { type: String, default: '' },
    canCompressContext: { type: Boolean, default: false },
  },
  emits: ['update:modelValue', 'send', 'attach', 'clear', 'remove-file', 'drop-files', 'compress-context'],
  data() {
    return { inputFocused: false, isDragging: false }
  },
  computed: {
    text: {
      get() { return this.modelValue },
      set(v) { this.$emit('update:modelValue', v) },
    },
    canSend() {
      return this.enabled && this.text.trim() && !this.inputError
    },
    resolvedPlaceholder() {
      return this.placeholder || this.$t('chatInput.placeholder')
    },
    effectiveContextLimit() {
      return this.contextLimit > 0 ? this.contextLimit : 128000
    },
    contextSummary() {
      return `${this.formatCount(this.contextUsed)} / ${this.formatCount(this.effectiveContextLimit)}`
    },
    usagePercent() {
      const ratio = this.effectiveContextLimit > 0 ? this.contextUsed / this.effectiveContextLimit : 0
      if (ratio <= 0) return 0
      return Math.min(100, Math.max(4, Math.round(ratio * 100)))
    },
    usageTone() {
      if (this.usagePercent >= 90) return 'danger'
      if (this.usagePercent >= 70) return 'warn'
      return 'normal'
    },
    contextMeterTitle() {
      return this.canCompressContext ? this.$t('chatInput.contextCompressHint') : this.$t('chatInput.contextEstimate')
    },
  },
  methods: {
    formatCount(value) {
      const num = Number(value || 0)
      if (!Number.isFinite(num) || num <= 0) return '0'
      if (num < 1000) return String(Math.round(num))
      if (num < 100000) return `${(num / 1000).toFixed(1)}K`
      return `${Math.round(num / 1000)}K`
    },
    autoResize() {
      const el = this.$refs.textarea
      if (!el) return
      el.style.height = 'auto'
      el.style.height = Math.min(Math.max(el.scrollHeight, 48), 200) + 'px'
    },
    onEnter(e) {
      if (!e.shiftKey && this.canSend) {
        e.preventDefault()
        this.$emit('send')
      }
    },
    focus() {
      this.$refs.textarea?.focus()
    },
    onDragOver() {
      if (this.uploadAvailable) this.isDragging = true
    },
    onDragLeave() {
      this.isDragging = false
    },
    onDrop(e) {
      this.isDragging = false
      if (!this.uploadAvailable) return
      const files = Array.from(e.dataTransfer?.files || [])
      if (files.length) this.$emit('drop-files', files)
    },
    resetHeight() {
      const el = this.$refs.textarea
      if (el) el.style.height = '48px'
    },
  },
}
</script>

<style scoped>
.mono-font { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); }
.input-area {
  position: absolute; bottom: 0; width: 100%; z-index: 20;
  padding: 0 24px 12px; display: flex; justify-content: center;
  background: linear-gradient(180deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.9) 20%, rgba(255,255,255,1) 100%);
}
.drop-overlay {
  position: absolute; inset: 0; z-index: 30;
  display: flex; align-items: center; justify-content: center;
  background: rgba(59, 130, 246, 0.08);
  border: 2px dashed rgba(59, 130, 246, 0.5);
  border-radius: var(--radius-lg, 18px);
  pointer-events: none;
}
.drop-overlay-content {
  padding: 8px 20px; border-radius: 12px;
  background: rgba(255,255,255,0.95); color: #2563eb;
  font-size: 14px; font-weight: 600;
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}
.input-wrapper { width: 100%; max-width: 880px; }
.input-container {
  background: var(--bg-app, #fff); border: 1px solid var(--border-base, #e4e4e7);
  border-radius: var(--radius-lg, 18px); box-shadow: var(--shadow-float);
  display: flex; flex-direction: column; transition: all 0.2s ease;
  padding: 12px 14px 10px;
}
.input-container.focused { border-color: var(--border-dark, #d4d4d8); box-shadow: var(--shadow-md); }

.input-error { padding: 6px 4px; font-size: 12px; color: #ef4444; }

.attached-files { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 4px 8px; }
.file-chip {
  display: flex; align-items: center; gap: 4px; padding: 4px 8px;
  background: var(--bg-hover, #f1f1f1); border: 1px solid var(--border-base, #e4e4e7);
  border-radius: 6px; font-size: 12px; color: var(--text-sec, #52525b);
}
.file-remove { background: none; border: none; cursor: pointer; color: var(--text-muted, #a1a1aa); font-size: 12px; padding: 0 2px; }
.file-remove:hover { color: #ef4444; }

.input-textarea {
  width: 100%; border: none; background: transparent; resize: none;
  font-size: 15px; outline: none; font-family: inherit; line-height: 1.5;
  color: var(--text-main, #18181b); max-height: 200px; overflow-y: auto;
  padding: 0 4px; min-height: 48px;
}
.input-textarea::placeholder { color: var(--text-muted, #a1a1aa); }
.input-textarea:disabled { opacity: 0.5; cursor: not-allowed; }

.input-toolbar {
  display: flex; justify-content: space-between; align-items: flex-end;
  margin-top: 8px; padding: 0 4px;
}

.toolbar-left { display: flex; align-items: center; gap: 8px; }
.toolbar-right { display: flex; align-items: flex-end; gap: 14px; }

.toolbar-icon-btn {
  width: 32px; height: 32px; border: none; background: transparent; border-radius: var(--radius-sm, 8px);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--text-sec, #52525b); transition: all 0.2s;
}
.toolbar-icon-btn:hover { background: var(--bg-hover, #f1f1f1); color: var(--text-main, #18181b); }
.toolbar-icon-btn.danger-hover:hover { background: #fee2e2; color: var(--danger-main, #ef4444); }

.context-meter {
  min-width: 168px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: none;
  background: transparent;
  padding: 0;
  text-align: left;
  cursor: pointer;
}

.context-meter:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.context-meter:not(:disabled):hover .context-value {
  color: #2563eb;
}

.context-meter-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.context-label {
  font-size: 11px;
  color: var(--text-muted, #a1a1aa);
  letter-spacing: 0.04em;
}

.context-value {
  font-size: 11px;
  color: var(--text-sec, #52525b);
  font-weight: 600;
}

.context-bar {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(226, 232, 240, 0.9);
}

.context-bar-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
  transition: width 0.2s ease, background 0.2s ease;
}

.context-bar-fill.warn {
  background: linear-gradient(90deg, #fbbf24, #f59e0b);
}

.context-bar-fill.danger {
  background: linear-gradient(90deg, #fb7185, #ef4444);
}

.btn-send {
  width: 36px; height: 36px; border: none; border-radius: var(--radius-sm, 8px); cursor: pointer;
  display: flex; align-items: center; justify-content: center; transition: all 0.2s;
  background: #e2e8f0; color: #94a3b8;
}
.btn-send.ready {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  box-shadow: 0 12px 24px -16px rgba(37, 99, 235, 0.75);
}
.btn-send.ready:hover { transform: translateY(-1px); box-shadow: 0 16px 28px -18px rgba(37, 99, 235, 0.85); }
.btn-send:disabled { cursor: not-allowed; opacity: 1; box-shadow: none; }
.btn-send.streaming { background: #ef4444; }
.btn-send.streaming:hover { background: #dc2626; }

@media (max-width: 768px) {
  .input-area {
    padding: 0 14px 8px;
  }

  .input-container {
    padding: 12px 12px 10px;
  }

  .input-toolbar {
    align-items: stretch;
    gap: 10px;
    flex-direction: column;
  }

  .toolbar-right {
    justify-content: space-between;
    width: 100%;
  }

  .context-meter {
    flex: 1;
    min-width: 0;
  }
}
</style>
