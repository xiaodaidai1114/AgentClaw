<template>
  <div class="tool-details-panel" :class="{ show: visible }">
    <div class="details-header mono-font">
      <span>{{ panelTitle }}</span>
      <button class="details-close" type="button" aria-label="Close details" @click="$emit('close')">✕</button>
    </div>
    <div class="details-body mono-font">
      <template v-if="isGroup">
        <div v-for="(item, index) in tool.tools" :key="item.id || index" class="tool-call-section">
          <div class="tool-call-title">{{ tool.name }} #{{ index + 1 }}</div>
          <div class="log-section">
            <span class="log-label">[Input]</span>
            <pre class="log-content input">{{ formatJson(item.arguments) }}</pre>
          </div>
          <div v-if="item.result" class="log-section">
            <span class="log-label">[Output]</span>
            <pre class="log-content output" :class="{ truncated: isOutputTruncated(item) && !isExpanded(item, index) }">{{ displayOutput(item, index) }}</pre>
            <button v-if="isOutputTruncated(item)" class="log-toggle" @click="toggleOutput(item, index)">{{ outputToggleText(item, index) }}</button>
          </div>
          <div v-if="item.duration_ms || item.elapsed" class="log-section">
            <span class="log-label">[Duration]</span>
            <span class="log-content duration">{{ formatDuration(item) }}</span>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="log-section">
          <span class="log-label">[Input]</span>
          <pre class="log-content input">{{ formatJson(tool.arguments) }}</pre>
        </div>
        <div v-if="tool.result" class="log-section">
          <span class="log-label">[Output]</span>
          <pre class="log-content output" :class="{ truncated: isOutputTruncated(tool) && !isExpanded(tool, 0) }">{{ displayOutput(tool, 0) }}</pre>
          <button v-if="isOutputTruncated(tool)" class="log-toggle" @click="toggleOutput(tool, 0)">{{ outputToggleText(tool, 0) }}</button>
        </div>
        <div v-if="tool.duration_ms || tool.elapsed" class="log-section">
          <span class="log-label">[Duration]</span>
          <span class="log-content duration">{{ formatDuration(tool) }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ToolDetailsPanel',
  props: {
    tool: { type: Object, required: true },
    visible: { type: Boolean, default: false },
  },
  emits: ['close'],
  data() {
    return { expandedOutputs: new Set() }
  },
  computed: {
    isGroup() {
      return !!this.tool?.isGroup && Array.isArray(this.tool?.tools)
    },
    panelTitle() {
      if (this.isGroup) return `${this.tool.name} ×${this.tool.tools.length}`
      return this.tool.id || this.tool.name
    },
  },
  methods: {
    formatJson(str) {
      if (!str) return ''
      try {
        return JSON.stringify(JSON.parse(str), null, 2)
      } catch {
        return str
      }
    },
    outputKey(tool, index) {
      return tool?.id || `${tool?.name || 'tool'}-${index}`
    },
    isExpanded(tool, index) {
      return this.expandedOutputs.has(this.outputKey(tool, index))
    },
    toggleOutput(tool, index) {
      const key = this.outputKey(tool, index)
      const next = new Set(this.expandedOutputs)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      this.expandedOutputs = next
    },
    isOutputTruncated(tool) {
      return String(tool?.result || '').length > 800
    },
    displayOutput(tool, index) {
      const output = String(tool?.result || '')
      if (!this.isOutputTruncated(tool) || this.isExpanded(tool, index)) return output
      return `${output.slice(0, 800)}\n…`
    },
    outputToggleText(tool, index) {
      if (this.isExpanded(tool, index)) return this.$t?.('toolDetails.collapseOutput') || 'Collapse output'
      const count = String(tool?.result || '').length
      return this.$t?.('toolDetails.expandOutput', { count }) || `Show full output (${count} chars)`
    },
    formatDuration(tool) {
      if (tool?.duration_ms) return `${tool.duration_ms.toFixed(0)}ms`
      return tool?.elapsed || ''
    },
  },
}
</script>

<style scoped>
.tool-details-panel {
  display: none; width: 100%; margin-top: 6px;
  background: var(--bg-terminal, #1e1e1e); border-radius: 10px;
  overflow: hidden; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
  animation: fadeIn 0.2s ease-out;
}
.tool-details-panel.show { display: block; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.details-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; background: #2d2d2d; color: #a3a3a3;
  font-size: 12px; border-bottom: 1px solid #404040;
}
.details-close {
  cursor: pointer; padding: 2px 4px; border-radius: 4px; transition: background 0.2s;
  border: 0; background: transparent; color: inherit; font: inherit;
}
.details-close:hover { background: #404040; color: white; }

.details-body {
  padding: 12px; font-size: 13px; line-height: 1.6;
  max-height: 300px; overflow-y: auto; overflow-x: auto;
}

.tool-call-section { padding-bottom: 14px; margin-bottom: 14px; border-bottom: 1px solid #334155; }
.tool-call-section:last-child { padding-bottom: 0; margin-bottom: 0; border-bottom: none; }
.tool-call-title { color: #93c5fd; font-weight: 700; margin-bottom: 8px; font-size: 12px; }
.log-section { margin-bottom: 12px; }
.log-section:last-child { margin-bottom: 0; }
.log-label { color: #8b5cf6; font-weight: bold; margin-bottom: 4px; display: block; }
.log-content { white-space: pre-wrap; word-break: break-all; margin: 0; }
.log-content.truncated { max-height: 180px; overflow: hidden; }
.log-toggle { margin-top: 6px; padding: 4px 8px; border: 1px solid #334155; border-radius: 6px; background: #111827; color: #93c5fd; cursor: pointer; font-size: 12px; font-family: inherit; }
.log-toggle:hover { background: #1f2937; color: #bfdbfe; }
.log-content.input { color: #d4d4d4; }
.log-content.output { color: #10b981; }
.log-content.duration { color: #f59e0b; }

.mono-font { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
</style>
