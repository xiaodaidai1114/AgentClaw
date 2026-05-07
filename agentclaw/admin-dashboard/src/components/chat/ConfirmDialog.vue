<template>
  <div v-if="visible" class="confirm-overlay" @click.self="cancel">
    <div class="confirm-dialog" tabindex="0" @keydown.enter.prevent="confirm" @keydown.esc.prevent="cancel">
      <div class="confirm-header">
        <span class="confirm-icon">⚠️</span>
        <h3>{{ $t('confirmDialog.title') }}</h3>
      </div>
      <div class="confirm-body">
        <div class="confirm-action">{{ action }}</div>
        <div v-if="description" class="confirm-description">{{ description }}</div>
        <div v-if="requireSudo" class="confirm-sudo">
          <label for="sudo-password">
            <span>🔐</span> <span>{{ $t('confirmDialog.sudoPassword') }}</span>
          </label>
          <input id="sudo-password" type="password" v-model="password" :placeholder="$t('confirmDialog.sudoPlaceholder')" @keydown.enter.prevent="confirm" :disabled="submitting" autofocus />
          <div class="sudo-hint">{{ $t('confirmDialog.sudoHint') }}</div>
        </div>
      </div>
      <div class="confirm-footer">
        <button class="btn-cancel" :disabled="submitting" @click="cancel">{{ $t('common.cancel') }}</button>
        <button class="btn-confirm" :disabled="submitting" @click="confirm">{{ $t('confirmDialog.confirm') }}</button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ConfirmDialog',
  props: {
    visible: { type: Boolean, default: false },
    action: { type: String, default: '' },
    description: { type: String, default: '' },
    requireSudo: { type: Boolean, default: false },
    submitting: { type: Boolean, default: false },
  },
  emits: ['confirm', 'cancel'],
  data() {
    return { password: '' }
  },
  watch: {
    visible(v) {
      if (!v) { this.password = ''; return }
      this.$nextTick(() => this.$el?.querySelector('.confirm-dialog')?.focus())
    },
  },
  methods: {
    confirm() {
      if (this.submitting) return
      this.$emit('confirm', this.password)
    },
    cancel() {
      if (this.submitting) return
      this.$emit('cancel')
    },
  },
}
</script>

<style scoped>
.confirm-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; backdrop-filter: blur(4px); }
.confirm-dialog { background: white; border-radius: 12px; width: 420px; max-width: 90vw; box-shadow: 0 20px 60px rgba(0,0,0,0.15); overflow: hidden; }
.confirm-header { padding: 20px 24px 12px; display: flex; align-items: center; gap: 10px; }
.confirm-header h3 { font-size: 16px; font-weight: 600; margin: 0; }
.confirm-body { padding: 0 24px 20px; }
.confirm-action { font-size: 14px; font-weight: 500; color: var(--text-main, #0f172a); margin-bottom: 8px; }
.confirm-description { font-size: 13px; color: var(--text-secondary, #475569); line-height: 1.5; }
.confirm-sudo { margin-top: 16px; }
.confirm-sudo label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.confirm-sudo input { width: 100%; padding: 8px 12px; border: 1px solid var(--border-color, #e2e8f0); border-radius: 8px; font-size: 14px; outline: none; }
.confirm-sudo input:focus { border-color: var(--accent-color, #3b82f6); box-shadow: 0 0 0 3px rgba(59,130,246,0.1); }
.sudo-hint { font-size: 11px; color: var(--text-muted, #94a3b8); margin-top: 6px; }
.confirm-footer { padding: 12px 24px; background: var(--bg-panel, #f8fafc); border-top: 1px solid var(--border-color, #e2e8f0); display: flex; justify-content: flex-end; gap: 8px; }
.btn-cancel, .btn-confirm { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: none; transition: all 0.2s; }
.btn-cancel { background: white; border: 1px solid var(--border-color, #e2e8f0); color: var(--text-secondary, #475569); }
.btn-cancel:hover { background: #f1f5f9; }
.btn-cancel:disabled, .btn-confirm:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-confirm { background: var(--primary-color, #0f172a); color: white; }
.btn-confirm:hover { background: var(--primary-hover, #1e293b); }
</style>
