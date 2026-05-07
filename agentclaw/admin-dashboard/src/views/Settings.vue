<template>
  <div>
    <PageHeader :title="t('settings.title')" :show-refresh="false" />

    <n-tabs v-model:value="activeTab" type="line" animated>
      <!-- Tab 1: 全局配置 -->
      <n-tab-pane name="global" :tab="t('settings.defaults')">
        <div class="settings-section">
          <n-card :title="t('settings.interface')" size="small" style="margin-bottom: 16px;">
            <n-form label-placement="left" label-width="180" size="small">
              <n-form-item :label="t('settings.language')">
                <LocaleSwitch />
                <n-text depth="3" class="form-hint">{{ t('settings.languageHint') }}</n-text>
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 运行时参数 -->
          <n-card :title="t('settings.runtime')" size="small" style="margin-bottom: 16px;">
            <n-text depth="3" style="display: block; margin-bottom: 12px;">
              {{ t('settings.runtimeHint') }}
            </n-text>
            <n-form :model="globalForm" label-placement="left" label-width="180" size="small">
              <n-form-item :label="t('settingsForm.global.defaultTimeout')">
                <div class="form-control-row">
                  <n-input-number v-model:value="globalForm.timeout" :min="0" :max="3600" class="form-input" />
                  <n-text depth="3" class="form-hint">{{ t('common.noLimit') }}</n-text>
                </div>
              </n-form-item>
              <n-form-item :label="t('settingsForm.global.recursionLimit')">
                <div class="form-control-row">
                  <n-input-number v-model:value="globalForm.recursion_limit" :min="1" :max="500" class="form-input" />
                </div>
              </n-form-item>
              <n-form-item :label="t('settingsForm.global.maxToolRounds')">
                <div class="form-control-row">
                  <n-input-number v-model:value="globalForm.max_tool_rounds" :min="0" :max="200" class="form-input" />
                  <n-text depth="3" class="form-hint">{{ t('common.noLimit') }}</n-text>
                </div>
              </n-form-item>
              <n-form-item :label="t('settingsForm.global.maxContextMessages')">
                <div class="form-control-row">
                  <n-input-number v-model:value="globalForm.max_context_messages" :min="0" :max="200" class="form-input" />
                  <n-text depth="3" class="form-hint">{{ t('settingsForm.hints.maxContextMessages') }}</n-text>
                </div>
              </n-form-item>
              <n-form-item :label="t('settingsForm.global.toolResultMaxLength')">
                <div class="form-control-row">
                  <n-input-number v-model:value="globalForm.tool_result_max_length" :min="1000" :max="100000" :step="1000" class="form-input" />
                </div>
              </n-form-item>
              <n-form-item :label="t('settingsForm.global.maxMessageLength')">
                <div class="form-control-row">
                  <n-input-number v-model:value="globalForm.max_message_length" :min="0" :max="100000" :step="1000" class="form-input" />
                  <n-text depth="3" class="form-hint">{{ t('common.noLimit') }}</n-text>
                </div>
              </n-form-item>
            </n-form>
            <template #header-extra>
              <n-button type="primary" size="small" @click="saveGlobalConfig" :disabled="!globalChanged">{{ t('common.save') }}</n-button>
            </template>
          </n-card>

          <!-- 基础设施 -->
          <n-card :title="t('settings.infra')" size="small">
            <n-collapse>
              <n-collapse-item :title="t('settingsForm.infra.database')" name="database">
                <template #header-extra>
                  <n-button text size="small" @click.stop="openInfraEdit('database')">{{ t('common.edit') }}</n-button>
                </template>
                <n-descriptions :column="2" label-placement="left" bordered size="small">
                  <n-descriptions-item :label="t('settingsForm.infra.host')">{{ infraConfig.database.host }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.port')">{{ infraConfig.database.port }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.user')">{{ infraConfig.database.user }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.databaseName')">{{ infraConfig.database.database }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.password')">***</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.poolMin')">{{ infraConfig.database.pool_min_size }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.poolMax')">{{ infraConfig.database.pool_max_size }}</n-descriptions-item>
                </n-descriptions>
              </n-collapse-item>

              <n-collapse-item title="Redis" name="redis">
                <template #header-extra>
                  <n-button text size="small" @click.stop="openInfraEdit('redis')">{{ t('common.edit') }}</n-button>
                </template>
                <n-descriptions :column="2" label-placement="left" bordered size="small">
                  <n-descriptions-item :label="t('settingsForm.infra.host')">{{ infraConfig.redis.host }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.port')">{{ infraConfig.redis.port }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.password')">***</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.maxConnections')">{{ infraConfig.redis.pool_max_connections }}</n-descriptions-item>
                </n-descriptions>
              </n-collapse-item>

              <n-collapse-item :title="t('settingsForm.infra.fileStorage')" name="upload">
                <template #header-extra>
                  <n-button text size="small" @click.stop="openInfraEdit('upload')">{{ t('common.edit') }}</n-button>
                </template>
                <n-descriptions :column="2" label-placement="left" bordered size="small">
                  <n-descriptions-item :label="t('settingsForm.infra.storageDir')">{{ infraConfig.upload.upload_dir }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.maxFileMb')">{{ infraConfig.upload.max_size_mb }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.minioEndpoint')">{{ infraConfig.upload.minio_endpoint || '-' }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.minioBucket')">{{ infraConfig.upload.minio_bucket }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.minioAccessKey')">{{ infraConfig.upload.minio_access_key ? '***' : '-' }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.minioSecure')">{{ infraConfig.upload.minio_secure ? t('common.yes') : t('common.no') }}</n-descriptions-item>
                </n-descriptions>
              </n-collapse-item>

              <n-collapse-item :title="t('settingsForm.infra.auth')" name="auth">
                <n-descriptions :column="2" label-placement="left" bordered size="small">
                  <n-descriptions-item :label="t('settingsForm.infra.adminToken')">{{ infraConfig.auth.admin_token || t('settingsForm.infra.unset') }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.workflowApiKey')">{{ infraConfig.auth.workflow_api_key || t('settingsForm.infra.unset') }}</n-descriptions-item>
                </n-descriptions>
                <n-text depth="3" style="font-size: 12px; margin-top: 8px; display: block;">{{ t('settingsForm.infra.authManagedByEnv') }}</n-text>
              </n-collapse-item>

              <n-collapse-item :title="t('settingsForm.infra.scheduler')" name="scheduler">
                <template #header-extra>
                  <n-button text size="small" @click.stop="openInfraEdit('scheduler')">{{ t('common.edit') }}</n-button>
                </template>
                <n-descriptions :column="2" label-placement="left" bordered size="small">
                  <n-descriptions-item :label="t('settingsForm.infra.enabled')">{{ infraConfig.scheduler.enabled ? t('common.yes') : t('common.no') }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.timezone')">{{ infraConfig.scheduler.timezone }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.maxWorkers')">{{ infraConfig.scheduler.max_workers }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.coalesce')">{{ infraConfig.scheduler.coalesce ? t('common.yes') : t('common.no') }}</n-descriptions-item>
                  <n-descriptions-item :label="t('settingsForm.infra.maxInstances')">{{ infraConfig.scheduler.max_instances }}</n-descriptions-item>
                </n-descriptions>
              </n-collapse-item>
            </n-collapse>
          </n-card>
        </div>
      </n-tab-pane>

      <!-- Tab 2: 内置智能体 -->
      <n-tab-pane name="builtinAgent" :tab="t('settings.builtinAgent.title')">
        <div class="settings-section builtin-agent-settings">
          <n-alert type="info" :bordered="false" style="margin-bottom: 16px;">
            {{ t('settings.builtinAgent.hint') }}
          </n-alert>

          <n-card :title="t('settings.builtinAgent.modelConfig')" size="small" style="margin-bottom: 16px;">
            <template #header-extra>
              <n-button type="primary" size="small" :loading="builtinNodeSaving" :disabled="!builtinNodeChanged" @click="saveBuiltinNodeConfig">{{ t('common.save') }}</n-button>
            </template>

            <n-form :model="builtinNodeForm" label-placement="left" label-width="180" size="small">
              <n-form-item :label="t('workflowConfig.fields.temperature')">
                <div class="form-control-row">
                  <n-input-number v-model:value="builtinNodeForm.temperature" :min="0" :max="2" :step="0.1" :placeholder="t('settings.builtinAgent.unsetParam')" class="form-input" @update:value="builtinNodeChanged = true" />
                  <n-button size="tiny" secondary class="reset-icon-button" :title="t('settings.builtinAgent.resetField')" :aria-label="t('settings.builtinAgent.resetField')" @click="resetBuiltinNodeField('temperature')"><span aria-hidden="true">↺</span></n-button>
                </div>
              </n-form-item>
              <n-form-item :label="t('workflowConfig.fields.topP')">
                <div class="form-control-row">
                  <n-input-number v-model:value="builtinNodeForm.top_p" :min="0" :max="1" :step="0.05" :placeholder="t('settings.builtinAgent.unsetParam')" class="form-input" @update:value="builtinNodeChanged = true" />
                  <n-button size="tiny" secondary class="reset-icon-button" :title="t('settings.builtinAgent.resetField')" :aria-label="t('settings.builtinAgent.resetField')" @click="resetBuiltinNodeField('top_p')"><span aria-hidden="true">↺</span></n-button>
                </div>
              </n-form-item>
              <n-form-item :label="t('workflowConfig.fields.fallbackModel')">
                <div class="form-control-row">
                  <n-select v-model:value="builtinNodeForm.fallback_model_id" :options="modelOptions" :placeholder="t('common.none')" clearable filterable class="form-input-wide" @update:value="builtinNodeChanged = true" />
                  <n-button size="tiny" secondary class="reset-icon-button" :title="t('settings.builtinAgent.resetField')" :aria-label="t('settings.builtinAgent.resetField')" @click="resetBuiltinNodeField('fallback_model_id')"><span aria-hidden="true">↺</span></n-button>
                </div>
              </n-form-item>
              <n-form-item :label="t('workflowConfig.fields.autoFallback')">
                <div class="form-control-row">
                  <n-switch v-model:value="builtinNodeForm.auto_fallback" @update:value="builtinNodeChanged = true" />
                  <n-button size="tiny" secondary class="reset-icon-button" :title="t('settings.builtinAgent.resetField')" :aria-label="t('settings.builtinAgent.resetField')" @click="resetBuiltinNodeField('auto_fallback')"><span aria-hidden="true">↺</span></n-button>
                </div>
              </n-form-item>
              <n-form-item :label="t('workflowConfig.fields.fallbackThreshold')">
                <div class="form-control-row">
                  <n-input-number v-model:value="builtinNodeForm.fallback_threshold" :min="0" :max="10" class="form-input" @update:value="builtinNodeChanged = true" />
                  <n-button size="tiny" secondary class="reset-icon-button" :title="t('settings.builtinAgent.resetField')" :aria-label="t('settings.builtinAgent.resetField')" @click="resetBuiltinNodeField('fallback_threshold')"><span aria-hidden="true">↺</span></n-button>
                </div>
              </n-form-item>
            </n-form>
          </n-card>

          <n-card :title="t('settings.builtinAgent.memoryConfig')" size="small">
            <template #header-extra>
              <n-button type="primary" size="small" :loading="builtinWorkflowSaving" :disabled="!builtinWorkflowChanged" @click="saveBuiltinWorkflowConfig">{{ t('common.save') }}</n-button>
            </template>

            <n-form :model="builtinWorkflowForm" label-placement="left" label-width="180" size="small">
              <n-form-item :label="t('workflowConfig.workflow.memory')">
                <div class="form-control-row form-control-column">
                  <n-input v-model:value="builtinWorkflowForm.memory_content" type="textarea" :rows="8" :placeholder="t('workflowConfig.workflow.memoryPlaceholder')" class="form-textarea-wide" @input="builtinWorkflowChanged = true" />
                  <div class="form-control-row">
                    <n-text depth="3" class="form-hint">{{ t('workflowConfig.workflow.memoryCounter', { count: builtinMemoryChars, max: builtinMemoryLimit }) }}</n-text>
                    <n-button size="tiny" secondary class="reset-icon-button" :title="t('settings.builtinAgent.resetField')" :aria-label="t('settings.builtinAgent.resetField')" @click="resetBuiltinWorkflowField('memory_content')"><span aria-hidden="true">↺</span></n-button>
                  </div>
                </div>
              </n-form-item>
            </n-form>
          </n-card>
        </div>
      </n-tab-pane>

      <!-- Tab 3: 模型配置 -->
      <n-tab-pane name="models" :tab="t('settings.modelConfig.title')">
        <div class="settings-section model-config-settings">
          <n-alert type="info" :bordered="false" style="margin-bottom: 16px;">
            {{ t('settings.modelConfig.hint') }}
            <n-text v-if="modelsConfigPath" code class="model-config-path">{{ modelsConfigPath }}</n-text>
          </n-alert>

          <n-card :title="t('settings.modelConfig.defaults')" size="small" style="margin-bottom: 16px;">
            <template #header-extra>
              <n-space :size="8">
                <n-button size="small" :loading="modelsConfigLoading" @click="fetchModelsConfig">{{ t('common.refresh') }}</n-button>
                <n-button type="primary" size="small" :loading="modelsConfigSaving" :disabled="!modelsConfigChanged" @click="saveModelsConfig">{{ t('common.save') }}</n-button>
              </n-space>
            </template>
            <n-form :model="modelsConfigForm" label-placement="left" label-width="160" size="small" class="model-default-form">
              <n-form-item :label="t('settings.modelConfig.defaultModel')">
                <n-select v-model:value="modelsConfigForm.default" :options="modelSelectOptions" :placeholder="t('common.none')" clearable filterable class="form-input-wide" @update:value="markModelsConfigChanged" />
              </n-form-item>
              <n-form-item :label="t('settings.modelConfig.fallbackModel')">
                <n-select v-model:value="modelsConfigForm.fallback" :options="modelSelectOptions" :placeholder="t('common.none')" clearable filterable class="form-input-wide" @update:value="markModelsConfigChanged" />
              </n-form-item>
              <n-form-item :label="t('settings.modelConfig.fastModel')">
                <n-select v-model:value="modelsConfigForm.fast" :options="modelSelectOptions" :placeholder="t('common.none')" clearable filterable class="form-input-wide" @update:value="markModelsConfigChanged" />
              </n-form-item>
              <n-form-item :label="t('settings.modelConfig.visionModel')">
                <n-select v-model:value="modelsConfigForm.vision" :options="visionModelSelectOptions" :placeholder="t('common.none')" clearable filterable class="form-input-wide" @update:value="markModelsConfigChanged" />
              </n-form-item>
            </n-form>
          </n-card>

          <n-card :title="t('settings.modelConfig.models')" size="small">
            <template #header-extra>
              <n-button size="small" secondary @click="openModelEditor()">{{ t('settings.modelConfig.addModel') }}</n-button>
            </template>
            <div v-if="modelsConfigForm.models.length" class="model-config-table">
              <div class="model-config-row model-config-row-head">
                <span>{{ t('settings.modelConfig.modelId') }}</span>
                <span>{{ t('settings.modelConfig.modelName') }}</span>
                <span>{{ t('settings.modelConfig.channel') }}</span>
                <span>{{ t('settings.modelConfig.type') }}</span>
                <span>{{ t('common.actions') }}</span>
              </div>
              <div v-for="(model, index) in modelsConfigForm.models" :key="model._key || index" class="model-config-row">
                <n-text strong class="model-config-cell">{{ model.id || t('settings.modelConfig.newModel') }}</n-text>
                <n-text class="model-config-cell model-name-cell" depth="3">{{ model.model || '-' }}</n-text>
                <n-tag size="small" :bordered="false">{{ model.channel || 'openai' }}</n-tag>
                <n-space :size="6">
                  <n-tag size="small" :bordered="false">{{ model.type || 'chat' }}</n-tag>
                  <n-tag v-if="model.supports_vision" type="info" size="small" :bordered="false">{{ t('settings.modelConfig.supportsVisionShort') }}</n-tag>
                </n-space>
                <n-space :size="8">
                  <n-button size="tiny" secondary @click="openModelEditor(index)">{{ t('common.edit') }}</n-button>
                  <n-button size="tiny" secondary type="error" @click="removeModelConfig(index)">{{ t('common.delete') }}</n-button>
                </n-space>
              </div>
            </div>
            <n-empty v-else :description="t('settings.modelConfig.noModels')" style="padding: 48px 0;" />
          </n-card>
        </div>
      </n-tab-pane>

      <!-- Tab 4: 环境配置 -->
      <n-tab-pane name="environment" :tab="t('settings.environment')">
        <div class="settings-section">
          <n-alert type="info" :bordered="false" style="margin-bottom: 16px;">
            {{ t('settings.environmentHint') }}
          </n-alert>

          <n-card :title="t('settings.advancedEnvironment')" size="small">
            <template #header-extra>
              <n-space :size="8">
                <n-button size="small" :loading="envLoading" @click="fetchEnvConfig">{{ t('common.refresh') }}</n-button>
                <n-button type="primary" size="small" :loading="envSaving" :disabled="!envChanged" @click="saveEnvConfig">{{ t('common.save') }}</n-button>
              </n-space>
            </template>

            <n-input
              v-model:value="envSearch"
              clearable
              :placeholder="t('settings.searchEnvPlaceholder')"
              style="max-width: 420px; margin-bottom: 16px;"
            />

            <n-empty v-if="!filteredEnvSections.length" :description="t('settings.noEnvironmentConfig')" style="padding: 48px 0;" />
            <n-collapse v-else>
              <n-collapse-item v-for="section in filteredEnvSections" :key="section.title" :title="envSectionTitle(section)" :name="section.title">
                <n-text v-for="line in envSectionDescription(section)" :key="line" depth="3" class="env-section-description">
                  {{ line }}
                </n-text>

                <div class="env-list">
                  <div v-for="variable in section.variables" :key="variable.name" class="env-setting-item">
                    <div class="env-setting-info">
                      <div class="env-setting-heading">
                        <n-text strong class="env-setting-title">{{ envVariableLabel(variable) }}</n-text>
                        <n-tag
                          v-if="variable.apply_scope !== 'immediate'"
                          size="small"
                          :type="applyScopeTagType(variable.apply_scope)"
                          :bordered="false"
                        >
                          {{ applyScopeLabel(variable.apply_scope) }}
                        </n-tag>
                      </div>
                      <div class="env-setting-meta">
                        <span class="env-variable-name">{{ variable.name }}</span>
                        <span>{{ sourceLabel(variable.source) }}</span>
                        <span v-if="variable.apply_scope === 'immediate'">{{ applyScopeLabel(variable.apply_scope) }}</span>
                      </div>
                      <n-text depth="3" class="env-description">{{ envVariableDescription(variable) }}</n-text>
                    </div>

                    <div class="env-setting-control">
                      <div class="env-control-row">
                        <n-switch
                          v-if="variable.type === 'boolean'"
                          v-model:value="envForm[variable.name]"
                        />
                        <n-select
                          v-else-if="variable.options && variable.options.length"
                          v-model:value="envForm[variable.name]"
                          :options="toEnvOptions(variable.options)"
                          clearable
                          filterable
                          class="env-input"
                        />
                        <n-input-number
                          v-else-if="variable.type === 'number'"
                          v-model:value="envForm[variable.name]"
                          class="env-input"
                        />
                        <n-input
                          v-else
                          v-model:value="envForm[variable.name]"
                          :type="variable.secret ? 'password' : 'text'"
                          :show-password-on="variable.secret ? 'click' : undefined"
                          :placeholder="variable.secret && variable.has_value ? t('settings.secretUnchanged') : ''"
                          class="env-input"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </n-collapse-item>
            </n-collapse>
          </n-card>
        </div>
      </n-tab-pane>

      <!-- Tab 2: 工作流配置 -->
      <n-tab-pane v-if="showScopedConfig" name="workflow" :tab="t('settings.workflowConfig')">
        <div class="settings-section">
          <n-select
            v-model:value="selectedWorkflowId"
            :options="workflowOptions"
            :placeholder="t('settings.selectWorkflow')"
            class="workflow-select"
            @update:value="onWorkflowSelect"
          />

          <template v-if="selectedWorkflowId && workflowConfig">
            <n-card size="small" style="margin-bottom: 16px;">
              <n-descriptions :column="2" label-placement="left" bordered size="small">
                <n-descriptions-item label="ID"><n-text code>{{ workflowConfig.id }}</n-text></n-descriptions-item>
                <n-descriptions-item :label="t('settingsForm.workflow.name')">{{ workflowConfig.name }}</n-descriptions-item>
                <n-descriptions-item :label="t('settingsForm.workflow.version')">{{ workflowConfig.version }}</n-descriptions-item>
                <n-descriptions-item :label="t('common.description')">{{ workflowConfig.description || '-' }}</n-descriptions-item>
              </n-descriptions>
            </n-card>

            <n-card :title="t('settings.runtimeConfig')" size="small">
              <template #header-extra>
                <n-button type="primary" size="small" @click="saveWorkflowConfig" :disabled="!workflowChanged">{{ t('common.save') }}</n-button>
              </template>
              <n-form :model="workflowForm" label-placement="left" label-width="160" size="small">
                <n-form-item :label="t('common.timeout')">
                  <n-input-number v-model:value="workflowForm.timeout" :min="0" :max="3600" class="form-input" @update:value="workflowChanged = true" />
                  <n-text depth="3" class="form-hint">{{ t('common.noLimit') }}</n-text>
                </n-form-item>
                <n-form-item :label="t('settingsForm.global.recursionLimit')">
                  <n-input-number v-model:value="workflowForm.recursion_limit" :min="1" :max="500" class="form-input" @update:value="workflowChanged = true" />
                </n-form-item>
                <n-form-item :label="t('settingsForm.workflow.cancelOnDisconnect')">
                  <n-switch v-model:value="workflowForm.cancel_on_disconnect" @update:value="workflowChanged = true" />
                </n-form-item>
                <n-form-item :label="t('settingsForm.workflow.tracing')">
                  <n-switch v-model:value="workflowForm.tracing" @update:value="workflowChanged = true" />
                </n-form-item>
                <n-form-item :label="t('settingsForm.workflow.authRequired')">
                  <n-switch v-model:value="workflowForm.auth_required" disabled />
                  <n-text depth="3" class="form-hint">{{ t('settingsForm.workflow.reservedAuthHint') }}</n-text>
                </n-form-item>
                <n-form-item :label="t('settingsForm.workflow.allowedRoles')">
                  <n-input v-model:value="workflowForm.allowed_roles" :placeholder="t('settingsForm.workflow.allowedRolesPlaceholder')" class="form-input-wide" disabled />
                  <n-text depth="3" class="form-hint">{{ t('settingsForm.workflow.reservedRolesHint') }}</n-text>
                </n-form-item>
                <n-form-item :label="t('settingsForm.workflow.rateLimit')">
                  <n-input v-model:value="workflowForm.rate_limit" :placeholder="t('settingsForm.workflow.rateLimitPlaceholder')" class="form-input" @input="workflowChanged = true" />
                  <n-text depth="3" class="form-hint">{{ t('settingsForm.workflow.publicRateLimitHint') }}</n-text>
                </n-form-item>
                <n-form-item :label="t('common.description')">
                  <n-input v-model:value="workflowForm.description" type="textarea" :rows="2" @input="workflowChanged = true" />
                </n-form-item>
                <n-form-item :label="t('workflowConfig.workflow.welcome')">
                  <n-input v-model:value="workflowForm.welcome" type="textarea" :rows="3" @input="workflowChanged = true" />
                </n-form-item>
              </n-form>
            </n-card>
          </template>

          <n-empty v-else :description="t('settings.selectWorkflowFirst')" style="padding: 80px 0;" />
        </div>
      </n-tab-pane>

      <!-- Tab 3: 节点配置 -->
      <n-tab-pane v-if="showScopedConfig" name="node" :tab="t('settings.nodeConfig')">
        <div class="settings-section">
          <n-space :size="12" style="margin-bottom: 16px;">
            <n-select
              v-model:value="nodeWorkflowId"
              :options="workflowOptions"
              :placeholder="t('settings.selectWorkflow')"
              class="workflow-select"
              @update:value="onNodeWorkflowSelect"
            />
          </n-space>

          <div v-if="nodeWorkflowId && nodeList.length" class="node-layout">
            <!-- 左侧节点列表 -->
            <n-card size="small" class="node-sidebar">
              <n-list hoverable clickable :show-divider="false">
                <n-list-item
                  v-for="node in nodeList"
                  :key="node.id"
                  :class="{ 'active-node': selectedNodeId === node.id }"
                  @click="onNodeSelect(node)"
                >
                  <n-space align="center" :size="8">
                    <n-tag :type="node.type === 'LLMNode' ? 'success' : node.type === 'HumanNode' ? 'warning' : 'info'" size="tiny">
                      {{ node.type_label }}
                    </n-tag>
                    <n-text>{{ node.id }}</n-text>
                  </n-space>
                </n-list-item>
              </n-list>
            </n-card>

            <!-- 右侧节点配置 -->
            <n-card v-if="selectedNodeId && nodeForm" size="small" class="node-editor">
              <template #header>
                <n-space align="center" :size="8">
                  <n-text strong>{{ selectedNodeId }}</n-text>
                  <n-tag :type="selectedNodeType === 'LLMNode' ? 'success' : 'info'" size="small">{{ selectedNodeType }}</n-tag>
                </n-space>
              </template>
              <template #header-extra>
                <n-button type="primary" size="small" @click="saveNodeConfig" :disabled="!nodeChanged">{{ t('common.save') }}</n-button>
              </template>

              <!-- 通用字段 -->
              <n-form :model="nodeForm" label-placement="left" label-width="180" size="small">
                <n-h6 prefix="bar" style="margin: 0 0 12px 0;">{{ t('settingsForm.node.generalConfig') }}</n-h6>
                <n-form-item :label="t('common.description')">
                  <n-input v-model:value="nodeForm.description" :placeholder="t('settingsForm.node.descriptionPlaceholder')" class="form-input-wide" @input="nodeChanged = true" />
                </n-form-item>
                <n-form-item :label="t('workflowConfig.fields.errorStrategy')">
                  <n-select v-model:value="nodeForm.on_error" :options="errorStrategyOptions" class="form-input" @update:value="nodeChanged = true" />
                </n-form-item>
                <n-form-item :label="t('settingsForm.node.maxRetries')">
                  <n-input-number v-model:value="nodeForm.max_retries" :min="0" :max="10" class="form-input" @update:value="nodeChanged = true" />
                </n-form-item>
                <n-form-item :label="t('settingsForm.node.retryDelay')">
                  <n-input-number v-model:value="nodeForm.retry_delay" :min="0" :max="60" :step="0.5" class="form-input" @update:value="nodeChanged = true" />
                </n-form-item>
                <n-form-item :label="t('workflowConfig.fields.outputToUser')">
                  <n-switch v-model:value="nodeForm.output_to_user" @update:value="nodeChanged = true" />
                </n-form-item>
                <n-form-item :label="t('workflowConfig.fields.outputKey')">
                  <n-input v-model:value="nodeForm.output_key" :placeholder="t('settingsForm.node.outputKeyPlaceholder')" class="form-input" @input="nodeChanged = true" />
                </n-form-item>
                <n-form-item :label="t('workflowConfig.fields.fallbackValue')">
                  <n-input v-model:value="nodeForm.fallback_value" :placeholder="t('settingsForm.node.fallbackValuePlaceholder')" class="form-input-wide" @input="nodeChanged = true" />
                </n-form-item>

                <!-- LLMNode 专属 -->
                <template v-if="selectedNodeType === 'LLMNode'">
                  <n-divider style="margin: 16px 0;" />
                  <n-h6 prefix="bar" style="margin: 0 0 12px 0;">{{ t('settingsForm.node.modelConfig') }}</n-h6>
                  <n-form-item :label="t('workflowConfig.fields.model')">
                    <n-select v-model:value="nodeForm.model_id" :options="modelOptions" :placeholder="t('settingsForm.node.useDefaultModel')" clearable class="form-input-wide" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.fastModel')">
                    <n-switch v-model:value="nodeForm.use_fast_model" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.temperature')">
                    <n-slider v-model:value="nodeForm.temperature" :min="0" :max="2" :step="0.1" class="form-slider" @update:value="nodeChanged = true" />
                    <n-text class="slider-value">{{ nodeForm.temperature }}</n-text>
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.maxTokens')">
                    <n-input-number v-model:value="nodeForm.max_tokens" :min="0" :max="200000" :step="256" class="form-input" @update:value="nodeChanged = true" />
                    <n-text depth="3" class="form-hint">{{ t('settingsForm.node.modelDefault') }}</n-text>
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.topP')">
                    <n-slider v-model:value="nodeForm.top_p" :min="0" :max="1" :step="0.05" class="form-slider" @update:value="nodeChanged = true" />
                    <n-text class="slider-value">{{ nodeForm.top_p }}</n-text>
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.stream')">
                    <n-switch v-model:value="nodeForm.stream" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.outputFormat')">
                    <n-select v-model:value="nodeForm.output_format" :options="outputFormatOptions" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>

                  <n-divider style="margin: 16px 0;" />
                  <n-h6 prefix="bar" style="margin: 0 0 12px 0;">{{ t('settingsForm.node.fallbackConfig') }}</n-h6>
                  <n-form-item :label="t('workflowConfig.fields.fallbackModel')">
                    <n-select v-model:value="nodeForm.fallback_model_id" :options="modelOptions" :placeholder="t('common.none')" clearable class="form-input-wide" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.autoFallback')">
                    <n-switch v-model:value="nodeForm.auto_fallback" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.fallbackThreshold')">
                    <n-input-number v-model:value="nodeForm.fallback_threshold" :min="0" :max="10" class="form-input" @update:value="nodeChanged = true" />
                    <n-text depth="3" class="form-hint">{{ t('settingsForm.node.failureThresholdHint') }}</n-text>
                  </n-form-item>

                  <n-divider style="margin: 16px 0;" />
                  <n-h6 prefix="bar" style="margin: 0 0 12px 0;">{{ t('settingsForm.node.toolsAndSkills') }}</n-h6>
                  <n-form-item :label="t('workflowConfig.fields.toolChoice')">
                    <n-select v-model:value="nodeForm.tool_choice" :options="toolChoiceOptions" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('settingsForm.global.maxToolRounds')">
                    <n-input-number v-model:value="nodeForm.max_tool_rounds" :min="0" :max="200" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.enableBuiltinSkills')">
                    <n-switch v-model:value="nodeForm.enable_builtin_skills" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.enableBuiltinTools')">
                    <n-switch v-model:value="nodeForm.enable_builtin_tools" @update:value="nodeChanged = true" />
                  </n-form-item>

                  <n-divider style="margin: 16px 0;" />
                  <n-h6 prefix="bar" style="margin: 0 0 12px 0;">{{ t('settingsForm.node.contextManagement') }}</n-h6>
                  <n-form-item :label="t('workflowConfig.fields.agentStyle')">
                    <n-select v-model:value="nodeForm.agent_style" :options="agentStyleOptions" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.useContext')">
                    <n-switch v-model:value="nodeForm.use_context" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.saveToContext')">
                    <n-switch v-model:value="nodeForm.save_to_context" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('settingsForm.global.maxContextMessages')">
                    <n-input-number v-model:value="nodeForm.max_context_messages" :min="0" :max="200" class="form-input" @update:value="nodeChanged = true" />
                    <n-text depth="3" class="form-hint">{{ t('settingsForm.hints.maxContextMessages') }}</n-text>
                  </n-form-item>
                  <n-form-item :label="t('settingsForm.node.contextCompression')">
                    <n-switch v-model:value="nodeForm.enable_compression" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('settingsForm.node.compressionThreshold')">
                    <n-input-number v-model:value="nodeForm.compression_threshold" :min="0" :max="500000" :step="10000" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('settingsForm.node.compressionModel')">
                    <n-select v-model:value="nodeForm.compression_model" :options="modelOptions" :placeholder="t('settingsForm.node.useDefault')" clearable class="form-input-wide" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.injectFiles')">
                    <n-select v-model:value="nodeForm.inject_files" :options="injectFilesOptions" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>
                </template>

                <template v-if="selectedNodeType === 'HumanNode'">
                  <n-divider style="margin: 16px 0;" />
                  <n-h6 prefix="bar" style="margin: 0 0 12px 0;">{{ t('settingsForm.node.humanNodeConfig') }}</n-h6>
                  <n-form-item :label="t('workflowConfig.fields.feedbackField')">
                    <n-input v-model:value="nodeForm.feedback_field" class="form-input" @input="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.pendingStatus')">
                    <n-input v-model:value="nodeForm.pending_status" class="form-input" @input="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.approvalMode')">
                    <n-switch v-model:value="nodeForm.approval_mode" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('common.timeout')">
                    <n-input-number v-model:value="nodeForm.timeout_seconds" :min="0" :max="86400" class="form-input" @update:value="nodeChanged = true" />
                    <n-text depth="3" class="form-hint">{{ t('common.noLimit') }}</n-text>
                  </n-form-item>
                  <n-form-item :label="t('workflowConfig.fields.timeoutAction')">
                    <n-select v-model:value="nodeForm.on_timeout" :options="timeoutActionOptions" class="form-input" @update:value="nodeChanged = true" />
                  </n-form-item>
                  <n-form-item :label="t('settingsForm.node.writeToContext')">
                    <n-switch v-model:value="nodeForm.save_to_context" @update:value="nodeChanged = true" />
                  </n-form-item>
                </template>
              </n-form>
            </n-card>

            <n-card v-else class="node-editor">
              <n-empty :description="t('settingsForm.node.selectNode')" style="padding: 80px 0;" />
            </n-card>
          </div>

          <n-empty v-else-if="nodeWorkflowId && !nodeList.length" :description="t('settingsForm.node.noNodes')" style="padding: 80px 0;" />
          <n-empty v-else :description="t('settings.selectWorkflowFirst')" style="padding: 80px 0;" />
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 模型编辑弹窗 -->
    <n-modal v-model:show="modelEditorVisible" preset="dialog" :title="modelEditorTitle" style="width: 90%; max-width: 560px;">
      <n-form :model="modelEditorForm" label-placement="left" label-width="120" size="small">
        <n-form-item :label="t('settings.modelConfig.modelId')">
          <n-input v-model:value="modelEditorForm.id" :placeholder="t('settings.modelConfig.modelIdPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('settings.modelConfig.channel')">
          <n-select v-model:value="modelEditorForm.channel" :options="modelChannelOptions" tag filterable />
        </n-form-item>
        <n-form-item :label="t('settings.modelConfig.type')">
          <n-select v-model:value="modelEditorForm.type" :options="modelTypeOptions" />
        </n-form-item>
        <n-form-item v-if="modelEditorForm.type === 'chat'" :label="t('settings.modelConfig.supportsVision')">
          <n-switch v-model:value="modelEditorForm.supports_vision" />
        </n-form-item>
        <n-form-item :label="t('settings.modelConfig.modelName')">
          <n-input v-model:value="modelEditorForm.model" :placeholder="t('settings.modelConfig.modelNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('settings.modelConfig.apiKey')">
          <div class="form-control-row form-control-column">
            <n-input v-model:value="modelEditorForm.api_key" type="password" show-password-on="click" :placeholder="modelEditorForm.api_key_set ? t('settings.modelConfig.apiKeyReplacementPlaceholder') : t('settings.modelConfig.apiKeyPlaceholder')" />
            <n-text v-if="modelEditorForm.api_key_set" depth="3" class="form-hint">{{ t('settings.modelConfig.apiKeyPreservedHint') }}</n-text>
          </div>
        </n-form-item>
        <n-form-item :label="t('settings.modelConfig.baseUrl')">
          <n-input v-model:value="modelEditorForm.base_url" :placeholder="t('settings.modelConfig.baseUrlPlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-button @click="modelEditorVisible = false">{{ $t('common.cancel') }}</n-button>
        <n-button type="primary" @click="saveModelEditor">{{ $t('common.save') }}</n-button>
      </template>
    </n-modal>

    <!-- 基础设施编辑弹窗 -->
    <n-modal v-model:show="infraEditVisible" preset="dialog" :title="infraEditTitle" style="width: 90%; max-width: 500px;">
      <n-form :model="infraEditForm" label-placement="left" label-width="160" size="small">
        <n-form-item v-for="field in infraEditFields" :key="field.key" :label="field.label">
          <n-input-number v-if="field.type === 'number'" v-model:value="infraEditForm[field.key]" :min="field.min" :max="field.max" style="width: 100%;" :disabled="field.readonly" />
          <n-switch v-else-if="field.type === 'boolean'" v-model:value="infraEditForm[field.key]" :disabled="field.readonly" />
          <n-input v-else v-model:value="infraEditForm[field.key]" :placeholder="field.placeholder" :disabled="field.readonly" />
          <n-text v-if="field.readonly" depth="3" class="form-hint">{{ t('settingsForm.infra.environmentVariable') }}</n-text>
        </n-form-item>
      </n-form>
      <template #action>
        <n-button @click="infraEditVisible = false">{{ $t('common.cancel') }}</n-button>
        <n-button type="primary" @click="saveInfraConfig">{{ $t('common.save') }}</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NTabs, NTabPane, NCard, NForm, NFormItem, NInputNumber, NInput,
  NSelect, NSwitch, NSlider, NButton, NText, NTag, NSpace,
  NDescriptions, NDescriptionsItem, NCollapse, NCollapseItem,
  NList, NListItem, NEmpty, NDivider, NModal, NH6, NAlert,
  useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import LocaleSwitch from '../components/LocaleSwitch.vue'
import { workflowsApi, modelsApi, settingsApi } from '../api'
import { toConversationModelOptions } from '../utils/models'

const message = useMessage()
const { t, tm } = useI18n()
const activeTab = ref('global')
const showScopedConfig = false

// ============================================================
// Mock data defaults
// ============================================================
const MOCK_GLOBAL = {
  timeout: 300,
  recursion_limit: 50,
  max_tool_rounds: 0,
  max_context_messages: 0,
  tool_result_max_length: 20000,
  max_message_length: 0,
}

const MOCK_INFRA = {
  database: { host: '127.0.0.1', port: 5432, user: 'postgres', database: 'agentclaw', pool_min_size: 2, pool_max_size: 10 },
  redis: { host: '127.0.0.1', port: 6379, pool_max_connections: 20 },
  upload: { upload_dir: './.storage', max_size_mb: 20, minio_endpoint: '', minio_access_key: '', minio_secret_key: '', minio_bucket: 'agentclaw', minio_secure: true },
  auth: { admin_token: '', workflow_api_key: '' },
  scheduler: { enabled: true, timezone: 'Asia/Shanghai', max_workers: 10, coalesce: true, max_instances: 1 },
}

// ============================================================
// Tab 1: 全局配置
// ============================================================
const globalForm = ref({ ...MOCK_GLOBAL })
const globalOriginal = ref({ ...MOCK_GLOBAL })
const infraConfig = ref(JSON.parse(JSON.stringify(MOCK_INFRA)))

const globalChanged = computed(() => JSON.stringify(globalForm.value) !== JSON.stringify(globalOriginal.value))

const envLoading = ref(false)
const envSaving = ref(false)
const envSearch = ref('')
const envConfig = ref({ sections: [] })
const envForm = ref({})
const envOriginal = ref({})
const envVariableMap = computed(() => {
  const variables = {}
  for (const section of envConfig.value.sections || []) {
    for (const variable of section.variables || []) {
      variables[variable.name] = variable
    }
  }
  return variables
})
const envChanged = computed(() => JSON.stringify(envForm.value) !== JSON.stringify(envOriginal.value))
const filteredEnvSections = computed(() => {
  const keyword = envSearch.value.trim().toLowerCase()
  const sections = envConfig.value.sections || []
  if (!keyword) return sections
  return sections
    .map(section => ({
      ...section,
      variables: (section.variables || []).filter(variable => {
        const haystack = [
          section.title,
          envSectionTitle(section),
          envSectionDescription(section).join(' '),
          variable.name,
          variable.label,
          variable.description,
          envVariableLabel(variable),
          envVariableDescription(variable),
        ].join(' ').toLowerCase()
        return haystack.includes(keyword)
      }),
    }))
    .filter(section => section.variables.length)
})

function normalizeGlobalValue(key, value) {
  if (value === null || value === undefined || value === '') return MOCK_GLOBAL[key]
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : MOCK_GLOBAL[key]
}

function normalizeGlobalWorkflow(workflow = {}) {
  return Object.fromEntries(
    Object.keys(MOCK_GLOBAL).map(key => [key, normalizeGlobalValue(key, workflow?.[key])])
  )
}

async function fetchGlobalConfig() {
  try {
    const res = await settingsApi.getGlobal()
    globalForm.value = normalizeGlobalWorkflow(res.workflow)
    globalOriginal.value = normalizeGlobalWorkflow(res.workflow)
    if (res.database) infraConfig.value.database = res.database
    if (res.redis) infraConfig.value.redis = res.redis
    if (res.upload) infraConfig.value.upload = res.upload
    if (res.auth) infraConfig.value.auth = res.auth
    if (res.scheduler) infraConfig.value.scheduler = res.scheduler
  } catch {
    // 后端未实现，使用 mock
  }
}

async function saveGlobalConfig() {
  try {
    const res = await settingsApi.updateGlobal(normalizeGlobalWorkflow(globalForm.value))
    globalForm.value = normalizeGlobalWorkflow(res.workflow)
    globalOriginal.value = normalizeGlobalWorkflow(res.workflow)
    message.success(t('settingsForm.messages.globalSaved'))
  } catch {
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  }
}

function normalizeEnvValue(variable) {
  if (!variable) return ''
  if (variable.secret) return variable.value ?? ''
  if (variable.type === 'boolean') return Boolean(variable.value)
  if (variable.type === 'number') {
    const number = Number(variable.value)
    return Number.isFinite(number) ? number : null
  }
  return variable.value ?? ''
}

function normalizeEnvSections(sections = []) {
  const values = {}
  for (const section of sections) {
    for (const variable of section.variables || []) {
      values[variable.name] = normalizeEnvValue(variable)
    }
  }
  return values
}

function applyEnvResponse(res = {}) {
  envConfig.value = { sections: res.sections || [] }
  const values = normalizeEnvSections(envConfig.value.sections)
  envForm.value = values
  envOriginal.value = { ...values }
}

function envI18nKey(value) {
  return String(value || '').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

function translatedText(key, fallback) {
  const value = t(key)
  return value === key ? fallback : value
}

function translatedList(key, fallback = []) {
  const value = tm(key)
  return Array.isArray(value) ? value : fallback
}

function envSectionTitle(section) {
  return translatedText(`settings.envSections.${envI18nKey(section.title)}.title`, section.title)
}

function envSectionDescription(section) {
  return translatedList(`settings.envSections.${envI18nKey(section.title)}.description`, section.description || [])
}

function envVariableLabel(variable) {
  return translatedText(`settings.envVars.${variable.name}.label`, variable.label || variable.name)
}

function envVariableDescription(variable) {
  return translatedText(`settings.envVars.${variable.name}.description`, variable.description || '')
}

async function fetchEnvConfig() {
  envLoading.value = true
  try {
    const res = await settingsApi.getEnv()
    applyEnvResponse(res)
  } catch {
    message.warning(t('settingsForm.messages.fetchEnvFailed'))
  } finally {
    envLoading.value = false
  }
}

function serializeEnvValue(variable, value) {
  if (variable?.type === 'boolean') return Boolean(value)
  if (variable?.type === 'number') return value ?? ''
  return value ?? ''
}

function changedEnvValues() {
  const values = {}
  for (const [name, value] of Object.entries(envForm.value)) {
    const variable = envVariableMap.value[name]
    if (!variable) continue
    if (JSON.stringify(value) === JSON.stringify(envOriginal.value[name])) continue
    if (variable.secret && value === '***') continue
    values[name] = serializeEnvValue(variable, value)
  }
  return values
}

async function saveEnvConfig() {
  const values = changedEnvValues()
  if (!Object.keys(values).length) return
  envSaving.value = true
  try {
    const res = await settingsApi.updateEnv({ values })
    applyEnvResponse(res)
    if (res.restart_required) {
      message.warning(t('settingsForm.messages.envSavedRestartRequired'))
    } else if (res.reconnect_required) {
      message.warning(t('settingsForm.messages.envSavedReconnectRequired'))
    } else {
      message.success(t('settingsForm.messages.envSaved'))
    }
  } catch {
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  } finally {
    envSaving.value = false
  }
}

function toEnvOptions(options = []) {
  return options.map(option => ({ label: option, value: option }))
}

function applyScopeLabel(scope) {
  const labels = {
    immediate: t('settings.applyImmediate'),
    reconnect: t('settings.applyReconnect'),
    restart: t('settings.applyRestart'),
  }
  return labels[scope] || t('settings.applyImmediate')
}

function applyScopeTagType(scope) {
  if (scope === 'restart') return 'warning'
  if (scope === 'reconnect') return 'info'
  return 'success'
}

function sourceLabel(source) {
  const labels = {
    environment: t('settings.sourceEnvironment'),
    project: t('settings.sourceProject'),
    default: t('settings.sourceDefault'),
    unset: t('settings.sourceUnset'),
  }
  return labels[source] || t('settings.sourceDefault')
}

// 模型配置
const MODEL_CONFIG_DEFAULTS = {
  default: '',
  fallback: '',
  fast: '',
  vision: '',
  models: [],
}
const MODEL_SECRET_MASK = '***'
const MODEL_REFERENCE_FIELDS = ['default', 'fallback', 'fast', 'vision']
let nextModelKey = 1
const modelsConfigPath = ref('')
const modelsConfigLoading = ref(false)
const modelsConfigSaving = ref(false)
const modelsConfigChanged = ref(false)
const modelsConfigForm = ref({ ...MODEL_CONFIG_DEFAULTS, models: [] })
const modelsConfigOriginal = ref({ ...MODEL_CONFIG_DEFAULTS, models: [] })
const modelEditorVisible = ref(false)
const modelEditorIndex = ref(-1)
const modelEditorForm = ref(cloneModelConfig())

const modelEditorTitle = computed(() =>
  modelEditorIndex.value >= 0 ? t('settings.modelConfig.editModel') : t('settings.modelConfig.addModel')
)

function isConversationModel(model = {}) {
  return model.type !== 'embedding' && model.type !== 'rerank'
}

const modelSelectOptions = computed(() =>
  modelsConfigForm.value.models
    .filter(model => model.id && isConversationModel(model))
    .map(model => ({
      label: `${model.id}${model.model ? ` (${model.model})` : ''}`,
      value: model.id,
    }))
)

const visionModelSelectOptions = computed(() =>
  modelsConfigForm.value.models
    .filter(model => model.id && isConversationModel(model) && model.supports_vision)
    .map(model => ({
      label: `${model.id}${model.model ? ` (${model.model})` : ''}`,
      value: model.id,
    }))
)

const modelChannelOptions = [
  { label: 'openai', value: 'openai' },
  { label: 'anthropic', value: 'anthropic' },
  { label: 'azure', value: 'azure' },
  { label: 'codex', value: 'codex' },
  { label: 'custom', value: 'custom' },
]

const modelTypeOptions = [
  { label: 'chat', value: 'chat' },
  { label: 'embedding', value: 'embedding' },
  { label: 'rerank', value: 'rerank' },
]

function cloneModelConfig(model = {}) {
  const rawType = model.type || model.model_type || 'chat'
  const legacyVision = rawType === 'vision'
  return {
    _key: nextModelKey++,
    id: model.id || '',
    channel: model.channel || 'openai',
    type: legacyVision ? 'chat' : rawType,
    supports_vision: !!(model.supports_vision || legacyVision),
    model: model.model || '',
    api_key: model.api_key === MODEL_SECRET_MASK ? '' : (model.api_key || ''),
    api_key_set: !!model.api_key_set,
    base_url: model.base_url || '',
    ...Object.fromEntries(
      Object.entries(model).filter(([key]) => !['_key', 'model_type', 'api_key'].includes(key))
    ),
  }
}

function normalizeModelsConfig(config = {}) {
  return {
    default: config.default || '',
    fallback: config.fallback || '',
    fast: config.fast || '',
    vision: config.vision || '',
    models: (config.models || []).map(cloneModelConfig),
  }
}

function serializeModelConfig(model = {}) {
  const payload = {}
  for (const [key, value] of Object.entries(model)) {
    if (key === '_key' || key === 'api_key_set') continue
    if (value === null || value === undefined || value === '') continue
    payload[key] = value
  }
  if (!payload.api_key && model.api_key_set) {
    payload.api_key = MODEL_SECRET_MASK
  }
  return payload
}

function serializeModelsConfig() {
  return {
    default: modelsConfigForm.value.default || '',
    fallback: modelsConfigForm.value.fallback || '',
    fast: modelsConfigForm.value.fast || '',
    vision: modelsConfigForm.value.vision || '',
    models: modelsConfigForm.value.models.map(serializeModelConfig),
  }
}

function applyModelsConfig(config = {}) {
  modelsConfigPath.value = config.path || ''
  const normalized = normalizeModelsConfig(config)
  modelsConfigForm.value = normalized
  modelsConfigOriginal.value = JSON.parse(JSON.stringify(normalized))
  modelsConfigChanged.value = false
}

async function fetchModelsConfig() {
  modelsConfigLoading.value = true
  try {
    const res = await settingsApi.getModelsConfig()
    applyModelsConfig(res)
  } catch {
    message.warning(t('settingsForm.messages.fetchModelsConfigFailed'))
  } finally {
    modelsConfigLoading.value = false
  }
}

async function saveModelsConfig() {
  modelsConfigSaving.value = true
  try {
    const res = await settingsApi.updateModelsConfig(serializeModelsConfig())
    applyModelsConfig(res)
    await fetchModels()
    message.success(t('settingsForm.messages.modelsSavedHotReloaded'))
  } catch {
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  } finally {
    modelsConfigSaving.value = false
  }
}

function markModelsConfigChanged() {
  modelsConfigChanged.value = true
}

function openModelEditor(index = -1) {
  modelEditorIndex.value = index
  modelEditorForm.value = cloneModelConfig(
    index >= 0
      ? modelsConfigForm.value.models[index]
      : { id: `model_${modelsConfigForm.value.models.length + 1}` }
  )
  modelEditorVisible.value = true
}

function saveModelEditor() {
  const modelId = String(modelEditorForm.value.id || '').trim()
  const modelName = String(modelEditorForm.value.model || '').trim()
  if (!modelId) {
    message.warning(t('settingsForm.messages.modelIdRequired'))
    return
  }
  if (!modelName) {
    message.warning(t('settingsForm.messages.modelNameRequired'))
    return
  }
  const nextModel = cloneModelConfig({
    ...modelEditorForm.value,
    id: modelId,
    model: modelName,
    supports_vision: modelEditorForm.value.type === 'chat' && !!modelEditorForm.value.supports_vision,
  })
  const index = modelEditorIndex.value
  if (index >= 0) {
    const current = modelsConfigForm.value.models[index] || {}
    nextModel._key = current._key || nextModel._key
    nextModel.api_key_set = !!(nextModel.api_key || current.api_key_set)
    modelsConfigForm.value.models.splice(index, 1, nextModel)
    if (current.id && current.id !== nextModel.id) {
      for (const field of MODEL_REFERENCE_FIELDS) {
        if (modelsConfigForm.value[field] === current.id) {
          modelsConfigForm.value[field] = nextModel.id
        }
      }
    }
  } else {
    nextModel.api_key_set = !!nextModel.api_key
    modelsConfigForm.value.models.push(nextModel)
  }
  modelEditorVisible.value = false
  modelsConfigChanged.value = true
}

function removeModelConfig(index) {
  const [removed] = modelsConfigForm.value.models.splice(index, 1)
  if (removed?.id) {
    for (const field of MODEL_REFERENCE_FIELDS) {
      if (modelsConfigForm.value[field] === removed.id) {
        modelsConfigForm.value[field] = ''
      }
    }
  }
  modelsConfigChanged.value = true
}

// 基础设施编辑
const infraEditVisible = ref(false)
const infraEditSection = ref('')
const infraEditForm = ref({})

const infraEditTitle = computed(() => {
  const titles = {
    database: t('settingsForm.infra.editDatabaseConfig'),
    redis: t('settingsForm.infra.editRedisConfig'),
    upload: t('settingsForm.infra.editFileStorageConfig'),
    scheduler: t('settingsForm.infra.editSchedulerConfig'),
  }
  return titles[infraEditSection.value] || t('settingsForm.infra.editConfig')
})

const infraFieldDefs = {
  database: [
    { key: 'host', label: t('settingsForm.infra.host'), type: 'string', readonly: true },
    { key: 'port', label: t('settingsForm.infra.port'), type: 'number', min: 1, max: 65535, readonly: true },
    { key: 'user', label: t('settingsForm.infra.user'), type: 'string', readonly: true },
    { key: 'database', label: t('settingsForm.infra.databaseName'), type: 'string', readonly: true },
    { key: 'pool_min_size', label: t('settingsForm.infra.poolMin'), type: 'number', min: 1, max: 50 },
    { key: 'pool_max_size', label: t('settingsForm.infra.poolMax'), type: 'number', min: 1, max: 100 },
  ],
  redis: [
    { key: 'host', label: t('settingsForm.infra.host'), type: 'string', readonly: true },
    { key: 'port', label: t('settingsForm.infra.port'), type: 'number', min: 1, max: 65535, readonly: true },
    { key: 'pool_max_connections', label: t('settingsForm.infra.maxConnections'), type: 'number', min: 1, max: 200 },
  ],
  upload: [
    { key: 'upload_dir', label: t('settingsForm.infra.storageDir'), type: 'string' },
    { key: 'max_size_mb', label: t('settingsForm.infra.maxFileMb'), type: 'number', min: 1, max: 500 },
    { key: 'minio_endpoint', label: t('settingsForm.infra.minioEndpoint'), type: 'string', readonly: true },
    { key: 'minio_access_key', label: t('settingsForm.infra.minioAccessKey'), type: 'string', readonly: true },
    { key: 'minio_secret_key', label: t('settingsForm.infra.minioSecretKey'), type: 'string', readonly: true },
    { key: 'minio_bucket', label: t('settingsForm.infra.minioBucket'), type: 'string' },
    { key: 'minio_secure', label: t('settingsForm.infra.minioSecure'), type: 'boolean' },
  ],
  scheduler: [
    { key: 'enabled', label: t('settingsForm.infra.enabled'), type: 'boolean' },
    { key: 'timezone', label: t('settingsForm.infra.timezone'), type: 'string' },
    { key: 'max_workers', label: t('settingsForm.infra.maxWorkers'), type: 'number', min: 1, max: 50 },
    { key: 'coalesce', label: t('settingsForm.infra.coalesce'), type: 'boolean' },
    { key: 'max_instances', label: t('settingsForm.infra.maxInstances'), type: 'number', min: 1, max: 20 },
  ],
}

const infraEditFields = computed(() => infraFieldDefs[infraEditSection.value] || [])

function openInfraEdit(section) {
  infraEditSection.value = section
  infraEditForm.value = { ...infraConfig.value[section] }
  infraEditVisible.value = true
}

async function saveInfraConfig() {
  try {
    const res = await settingsApi.updateInfra(infraEditSection.value, infraEditForm.value)
    infraConfig.value[infraEditSection.value] = { ...res }
    infraEditVisible.value = false
    message.success(t('settingsForm.messages.configSaved'))
  } catch {
    infraConfig.value[infraEditSection.value] = { ...infraEditForm.value }
    infraEditVisible.value = false
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  }
}

// ============================================================
// Tab 2: 工作流配置
// ============================================================
const workflows = ref([])
const selectedWorkflowId = ref(null)
const workflowConfig = ref(null)
const workflowForm = ref({})
const workflowChanged = ref(false)

const workflowOptions = computed(() =>
  workflows.value.map(wf => ({ label: `${wf.name || wf.id} (${wf.id})`, value: wf.id }))
)

async function fetchWorkflows() {
  try {
    const res = await workflowsApi.list()
    workflows.value = (res.workflows || []).filter(wf => wf.id !== '__builtin__')
  } catch (e) {
    console.error('Failed to fetch workflows:', e)
  }
}

async function onWorkflowSelect(workflowId) {
  if (!workflowId) {
    workflowConfig.value = null
    return
  }
  try {
    const detail = await workflowsApi.get(workflowId)
    const workflow = normalizeWorkflowDetail(detail)
    workflowConfig.value = workflow
    try {
      const cfg = await settingsApi.getWorkflow(workflowId)
      workflowForm.value = { ...cfg }
    } catch {
      workflowForm.value = {
        timeout: workflow.timeout ?? 300,
        recursion_limit: workflow.recursion_limit ?? 50,
        cancel_on_disconnect: workflow.cancel_on_disconnect ?? true,
        tracing: workflow.tracing ?? true,
        auth_required: workflow.auth_required ?? false,
        allowed_roles: Array.isArray(workflow.allowed_roles) ? workflow.allowed_roles.join(', ') : (workflow.allowed_roles || ''),
        rate_limit: workflow.rate_limit || '',
        public_share_enabled: !!workflow.public_share_enabled,
        public_share_token: workflow.public_share_token || '',
        workflow_api_key: '',
        workflow_api_key_set: !!workflow.workflow_api_key_set,
        public_conversation_limit: workflow.public_conversation_limit || 20,
        public_message_limit: workflow.public_message_limit || 200,
        description: workflow.description || '',
        welcome: workflow.welcome || '',
      }
    }
    workflowChanged.value = false
  } catch (e) {
    message.error(t('settingsForm.messages.fetchWorkflowFailed'))
  }
}

async function saveWorkflowConfig() {
  try {
    const res = await settingsApi.updateWorkflow(selectedWorkflowId.value, workflowForm.value)
    workflowForm.value = { ...res }
    workflowChanged.value = false
    message.success(t('settingsForm.messages.workflowSaved'))
  } catch {
    workflowChanged.value = false
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  }
}

// ============================================================
// Tab 3: 节点配置
// ============================================================
const nodeWorkflowId = ref(null)
const nodeList = ref([])
const selectedNodeId = ref(null)
const selectedNodeType = ref('')
const nodeForm = ref(null)
const nodeChanged = ref(false)
const availableModels = ref([])

const modelOptions = computed(() => toConversationModelOptions(availableModels.value))

const errorStrategyOptions = [
  { label: 'ABORT', value: 'ABORT' },
  { label: 'RETRY', value: 'RETRY' },
  { label: 'SKIP', value: 'SKIP' },
  { label: 'FALLBACK', value: 'FALLBACK' },
]

const toolChoiceOptions = [
  { label: 'auto', value: 'auto' },
  { label: 'required', value: 'required' },
  { label: 'none', value: 'none' },
]

const timeoutActionOptions = [
  { label: 'approve', value: 'approve' },
  { label: 'reject', value: 'reject' },
  { label: 'error', value: 'error' },
]

const agentStyleOptions = [
  { label: 'default', value: 'default' },
  { label: 'agentic', value: 'agentic' },
]

const outputFormatOptions = [
  { label: 'text', value: 'text' },
  { label: 'json', value: 'json' },
]

const injectFilesOptions = [
  { label: t('workflowConfig.injectFiles.inheritDefault'), value: null },
  { label: t('workflowConfig.injectFiles.forceOn'), value: true },
  { label: t('workflowConfig.injectFiles.forceOff'), value: false },
]

const BUILTIN_WORKFLOW_ID = '__builtin__'
const BUILTIN_AGENT_NODE_ID = 'agent'
const builtinMemoryLimit = 40000
const builtinLoading = ref(false)
const builtinWorkflowSaving = ref(false)
const builtinNodeSaving = ref(false)
const builtinWorkflowChanged = ref(false)
const builtinNodeChanged = ref(false)
const builtinWorkflowForm = ref({
  memory_content: '',
  memory_chars: 0,
  memory_over_limit: false,
})
const BUILTIN_NODE_DEFAULTS = {
  temperature: null,
  top_p: null,
  fallback_model_id: null,
  auto_fallback: false,
  fallback_threshold: 3,
}
const BUILTIN_WORKFLOW_DEFAULTS = {
  memory_content: '',
  memory_chars: 0,
  memory_over_limit: false,
}
const builtinNodeForm = ref({ ...BUILTIN_NODE_DEFAULTS })
const builtinMemoryChars = computed(() => (builtinWorkflowForm.value.memory_content || '').length)

function normalizeBuiltinWorkflowConfig(config = {}) {
  const memory = config.memory_content || ''
  return {
    memory_content: memory,
    memory_chars: config.memory_chars ?? memory.length,
    memory_over_limit: !!config.memory_over_limit,
  }
}

function normalizeBuiltinNodeConfig(config = {}) {
  return {
    temperature: config.temperature ?? null,
    top_p: config.top_p ?? null,
    fallback_model_id: config.fallback_model_id || null,
    auto_fallback: !!config.auto_fallback,
    fallback_threshold: config.fallback_threshold ?? 3,
  }
}

async function fetchBuiltinAgentConfig() {
  builtinLoading.value = true
  try {
    const [workflowConfig, nodeConfig] = await Promise.all([
      settingsApi.getWorkflow(BUILTIN_WORKFLOW_ID),
      settingsApi.getNode(BUILTIN_WORKFLOW_ID, BUILTIN_AGENT_NODE_ID),
    ])
    builtinWorkflowForm.value = normalizeBuiltinWorkflowConfig(workflowConfig)
    builtinNodeForm.value = normalizeBuiltinNodeConfig(nodeConfig)
    builtinWorkflowChanged.value = false
    builtinNodeChanged.value = false
  } catch {
    message.error(t('settingsForm.messages.fetchBuiltinAgentFailed'))
  } finally {
    builtinLoading.value = false
  }
}

async function saveBuiltinWorkflowConfig() {
  builtinWorkflowSaving.value = true
  try {
    const res = await settingsApi.updateWorkflow(BUILTIN_WORKFLOW_ID, {
      memory_content: builtinWorkflowForm.value.memory_content || '',
    })
    builtinWorkflowForm.value = normalizeBuiltinWorkflowConfig(res)
    builtinWorkflowChanged.value = false
    message.success(t('settingsForm.messages.builtinAgentSaved'))
  } catch {
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  } finally {
    builtinWorkflowSaving.value = false
  }
}

async function saveBuiltinNodeConfig() {
  builtinNodeSaving.value = true
  try {
    const res = await settingsApi.updateNode(BUILTIN_WORKFLOW_ID, BUILTIN_AGENT_NODE_ID, builtinNodeForm.value)
    builtinNodeForm.value = normalizeBuiltinNodeConfig(res)
    builtinNodeChanged.value = false
    message.success(t('settingsForm.messages.builtinAgentSaved'))
  } catch {
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  } finally {
    builtinNodeSaving.value = false
  }
}

function resetBuiltinWorkflowField(field) {
  if (!(field in BUILTIN_WORKFLOW_DEFAULTS)) return
  builtinWorkflowForm.value = {
    ...builtinWorkflowForm.value,
    [field]: BUILTIN_WORKFLOW_DEFAULTS[field],
  }
  if (field === 'memory_content') {
    builtinWorkflowForm.value.memory_chars = 0
    builtinWorkflowForm.value.memory_over_limit = false
  }
  builtinWorkflowChanged.value = true
  message.info(t('settingsForm.messages.fieldResetPending'))
}

function resetBuiltinNodeField(field) {
  if (!(field in BUILTIN_NODE_DEFAULTS)) return
  builtinNodeForm.value = {
    ...builtinNodeForm.value,
    [field]: BUILTIN_NODE_DEFAULTS[field],
  }
  builtinNodeChanged.value = true
  message.info(t('settingsForm.messages.fieldResetPending'))
}

function getNodeTypeLabel(type) {
  const map = { LLMNode: 'LLM', HumanNode: 'Human', FunctionNode: 'Function', CustomNode: 'Custom', MCPNode: 'MCP', SyncNode: 'Sync', DocumentNode: 'Document', SubWorkflowNode: 'SubWorkflow' }
  return map[type] || type || 'Node'
}

function normalizeWorkflowDetail(detail) {
  return detail?.workflow || detail || {}
}

function normalizeNodeType(type) {
  const value = String(type || '').toLowerCase()
  if (value.includes('llm')) return 'LLMNode'
  if (value.includes('human')) return 'HumanNode'
  if (value.includes('function')) return 'FunctionNode'
  if (value.includes('mcp')) return 'MCPNode'
  if (value.includes('document')) return 'DocumentNode'
  if (value.includes('subworkflow')) return 'SubWorkflowNode'
  if (value.includes('sync')) return 'SyncNode'
  return type || 'BaseNode'
}

async function onNodeWorkflowSelect(workflowId) {
  selectedNodeId.value = null
  nodeForm.value = null
  nodeList.value = []
  if (!workflowId) return

  try {
    const detail = await workflowsApi.get(workflowId)
    const workflow = normalizeWorkflowDetail(detail)
    nodeList.value = (workflow.nodes || []).map(n => ({
      id: n.id || n.name,
      type: normalizeNodeType(n.type),
      type_label: getNodeTypeLabel(normalizeNodeType(n.type)),
      config: n,
    }))
  } catch (e) {
    message.error(t('settingsForm.messages.fetchNodesFailed'))
  }
}

async function onNodeSelect(node) {
  selectedNodeId.value = node.id
  selectedNodeType.value = node.type
  nodeChanged.value = false

  try {
    const cfg = await settingsApi.getNode(nodeWorkflowId.value, node.id)
    nodeForm.value = { ...cfg }
  } catch {
    const c = node.config || {}
    const base = {
      description: c.description || '',
      on_error: c.on_error || 'ABORT',
      max_retries: c.max_retries ?? 3,
      retry_delay: c.retry_delay ?? 1.0,
      output_to_user: c.output_to_user ?? true,
      output_key: c.output_key || '',
      fallback_value: c.fallback_value || '',
    }
    if (node.type === 'LLMNode') {
      const params = c.model_params || {}
      nodeForm.value = {
        ...base,
        output_to_user: c.output_to_user ?? false,
        // 模型配置
        model_id: c.model_id || null,
        use_fast_model: c.use_fast_model ?? false,
        temperature: params.temperature ?? 0.7,
        max_tokens: params.max_tokens ?? 0,
        top_p: params.top_p ?? 1,
        stream: c.stream ?? false,
        output_format: c.output_format || 'text',
        // Fallback
        fallback_model_id: c.fallback_model_id || null,
        auto_fallback: c.auto_fallback ?? false,
        fallback_threshold: c.fallback_threshold ?? 3,
        // 工具与技能
        tool_choice: c.tool_choice || 'auto',
        max_tool_rounds: c.max_tool_rounds ?? 0,
        enable_builtin_skills: c.enable_builtin_skills ?? false,
        enable_builtin_tools: c.enable_builtin_tools ?? false,
        // 上下文
        agent_style: c.agent_style || 'default',
        use_context: c.use_context ?? true,
        save_to_context: c.save_to_context ?? true,
        max_context_messages: c.max_context_messages ?? 0,
        enable_compression: c.enable_compression ?? true,
        compression_threshold: c.compression_threshold ?? 100000,
        compression_model: c.compression_model || null,
        inject_files: c.inject_files ?? null,
      }
    } else if (node.type === 'HumanNode') {
      nodeForm.value = {
        ...base,
        feedback_field: c.feedback_field || 'feedback',
        pending_status: c.pending_status || 'pending',
        approval_mode: c.approval_mode ?? false,
        timeout_seconds: c.timeout_seconds ?? 0,
        on_timeout: c.on_timeout || 'error',
        save_to_context: c.save_to_context ?? true,
      }
    } else {
      nodeForm.value = base
    }
  }
}

async function saveNodeConfig() {
  try {
    const res = await settingsApi.updateNode(nodeWorkflowId.value, selectedNodeId.value, nodeForm.value)
    nodeForm.value = { ...res }
    nodeChanged.value = false
    message.success(t('settingsForm.messages.nodeSaved'))
  } catch {
    nodeChanged.value = false
    message.warning(t('settingsForm.messages.backendNotPersisted'))
  }
}

async function fetchModels() {
  try {
    const res = await modelsApi.getAvailable()
    availableModels.value = res.models || []
  } catch {
    availableModels.value = []
  }
}

// ============================================================
// Init
// ============================================================
onMounted(() => {
  fetchGlobalConfig()
  fetchEnvConfig()
  fetchModels()
  fetchModelsConfig()
  fetchBuiltinAgentConfig()
})

// 同步工作流选择到节点 tab
watch(activeTab, (tab) => {
  if (tab === 'node' && selectedWorkflowId.value && !nodeWorkflowId.value) {
    nodeWorkflowId.value = selectedWorkflowId.value
    onNodeWorkflowSelect(selectedWorkflowId.value)
  }
})
</script>

<style scoped>
.settings-section {
  width: 100%;
}

.workflow-select {
  width: 100%;
  max-width: 360px;
  margin-bottom: 16px;
}

.form-input {
  width: 100%;
  max-width: 220px;
}

.form-input-wide {
  width: 100%;
  max-width: 320px;
}

.form-control-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  width: 100%;
}

.form-control-row .form-input {
  flex: 0 0 220px;
}

.form-control-column {
  align-items: flex-start;
  flex-direction: column;
}

.form-textarea-wide {
  width: 100%;
  max-width: 760px;
}

.reset-icon-button {
  width: 28px;
  min-width: 28px;
  padding: 0;
  font-size: 14px;
  line-height: 1;
}

.form-hint {
  font-size: 12px;
  white-space: normal;
  overflow-wrap: anywhere;
}

.model-config-path {
  display: inline-block;
  margin-left: 8px;
}

.model-default-form {
  width: 100%;
}

.model-config-table {
  display: grid;
  width: 100%;
  overflow-x: auto;
}

.model-config-row {
  display: grid;
  grid-template-columns: minmax(140px, 1.1fr) minmax(180px, 1.4fr) minmax(100px, 0.8fr) minmax(140px, 0.9fr) minmax(120px, auto);
  gap: 12px;
  align-items: center;
  min-width: 700px;
  padding: 12px 0;
  border-bottom: 1px solid var(--n-border-color);
}

.model-config-row:last-child {
  border-bottom: 0;
}

.model-config-row-head {
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 600;
  padding-top: 0;
}

.model-config-cell {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-name-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

.env-section-description {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
}

.env-list {
  margin-top: 12px;
  border-top: 1px solid var(--n-border-color);
}

.env-setting-item {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(280px, 420px);
  gap: 16px 24px;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid var(--n-border-color);
}

.env-setting-info {
  min-width: 0;
}

.env-setting-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.env-setting-title {
  min-width: 0;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-setting-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0;
  margin-top: 4px;
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 1.5;
}

.env-setting-meta span:not(:first-child)::before {
  content: "·";
  margin: 0 6px;
  color: var(--n-text-color-disabled);
}

.env-variable-name {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  letter-spacing: 0.01em;
}

.env-description {
  display: -webkit-box;
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.env-setting-control {
  min-width: 0;
}

.env-control-row {
  display: flex;
  align-items: center;
  width: 100%;
}

.env-input {
  width: 100%;
  max-width: none;
}

@media (max-width: 900px) {
  .env-setting-item {
    grid-template-columns: 1fr;
  }
}

.form-slider {
  width: 100%;
  max-width: 220px;
}

.slider-value {
  margin-left: 12px;
  width: 40px;
  text-align: right;
  flex-shrink: 0;
}

.node-layout {
  display: flex;
  gap: 16px;
  min-height: calc(100vh - 200px);
}

.node-sidebar {
  width: 240px;
  flex-shrink: 0;
}

.node-sidebar :deep(.n-list-item) {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 2px;
}

.active-node {
  background: var(--primary-light, #e8f4fd);
}

.node-editor {
  flex: 1;
  min-width: 0;
}

/* 大屏幕：全局配置和节点配置双列表单 */
@media (min-width: 1200px) {
  .settings-section :deep(.n-form) {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0 32px;
  }
  .settings-section :deep(.n-form .n-h6),
  .settings-section :deep(.n-form .n-divider) {
    grid-column: 1 / -1;
  }
  .settings-section.builtin-agent-settings :deep(.n-form) {
    display: block;
  }
}

@media (max-width: 768px) {
  .workflow-select {
    max-width: 100%;
  }
  .node-layout {
    flex-direction: column;
    min-height: auto;
  }
  .node-sidebar {
    width: 100%;
  }
  .form-input,
  .form-input-wide,
  .form-slider {
    max-width: 100%;
  }
}
</style>
