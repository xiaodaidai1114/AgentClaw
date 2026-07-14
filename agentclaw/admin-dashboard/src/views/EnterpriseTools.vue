<template>
  <div class="enterprise-tools">
    <div class="header">
      <h2>🔧 企业工具</h2>
      <n-button type="primary" @click="openCreate">+ 导入工具</n-button>
    </div>
    <n-data-table :columns="columns" :data="tools" :bordered="false" :loading="loading" />

    <!-- 导入/编辑 Modal -->
    <n-modal v-model:show="showCreate" preset="card" :title="editName ? '编辑工具' : '导入工具'" style="width: 660px">
      <n-form :model="form" label-placement="top" size="small">
        <n-form-item label="工具名（snake_case，字母开头）">
          <n-input v-model:value="form.name" placeholder="query_order" />
        </n-form-item>
        <n-form-item label="描述（AI 看这个决定何时调用，写清楚做什么+何时用）">
          <n-input v-model:value="form.description" type="textarea" :rows="2" placeholder="根据订单号查询订单状态" />
        </n-form-item>
        <n-form-item label="handler 类型">
          <n-select v-model:value="form.handler.type" :options="handlerTypeOptions" />
        </n-form-item>
        <template v-if="form.handler.type === 'python'">
          <n-form-item label="module"><n-input v-model:value="form.handler.module" placeholder="my_company.tools.reports" /></n-form-item>
          <n-form-item label="function"><n-input v-model:value="form.handler.function" placeholder="monthly_report" /></n-form-item>
        </template>
        <template v-if="form.handler.type === 'http'">
          <n-form-item label="method"><n-input v-model:value="form.handler.method" placeholder="GET" /></n-form-item>
          <n-form-item label="url（{param} 占位）"><n-input v-model:value="form.handler.url" placeholder="https://api/orders/{order_id}" /></n-form-item>
          <n-form-item label="auth_env（环境变量名，密钥不进配置）"><n-input v-model:value="form.handler.auth_env" placeholder="ORDER_API_KEY" /></n-form-item>
        </template>
        <template v-if="form.handler.type === 'cli'">
          <n-form-item label="command"><n-input v-model:value="form.handler.command" placeholder="ping" /></n-form-item>
          <n-form-item label="args（逗号分隔，{param} 占位）"><n-input v-model:value="form.handlerArgsStr" placeholder="-n,4,{host}" /></n-form-item>
        </template>
        <n-form-item label="input_schema（JSON Schema）">
          <n-input v-model:value="form.inputSchemaStr" type="textarea" :rows="5" placeholder='{"type":"object","properties":{"x":{"type":"string"}},"required":["x"]}' />
        </n-form-item>
        <n-form-item label="permission">
          <n-select v-model:value="form.permission" :options="permissionOptions" />
        </n-form-item>
        <n-form-item label="domain（可选）"><n-input v-model:value="form.domain" placeholder="sales" /></n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="showCreate = false">取消</n-button>
        <n-button type="primary" :loading="saving" @click="saveTool">保存</n-button>
      </template>
    </n-modal>

    <!-- 测试 Modal -->
    <n-modal v-model:show="showTest" preset="card" :title="`测试 ${testName}`" style="width: 580px">
      <n-form-item label="arguments（JSON）">
        <n-input v-model:value="testArgsStr" type="textarea" :rows="4" placeholder='{"order_id":"ORD123"}' />
      </n-form-item>
      <n-form-item label="结果">
        <n-input :value="testResult" type="textarea" :rows="7" readonly />
      </n-form-item>
      <template #footer>
        <n-button @click="showTest = false">关闭</n-button>
        <n-button type="primary" :loading="testing" @click="runTest">执行</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { NDataTable, NButton, NModal, NForm, NFormItem, NInput, NSelect, NSpace, useMessage } from 'naive-ui'
import { enterpriseToolsApi } from '../api'

const message = useMessage()
const tools = ref([])
const loading = ref(false)
const showCreate = ref(false)
const showTest = ref(false)
const saving = ref(false)
const testing = ref(false)
const editName = ref('')
const form = ref(emptyForm())
const testName = ref('')
const testArgsStr = ref('{}')
const testResult = ref('')

const handlerTypeOptions = [
  { label: 'python（Python 函数）', value: 'python' },
  { label: 'http（HTTP API）', value: 'http' },
  { label: 'cli（命令行/脚本）', value: 'cli' },
]
const permissionOptions = [
  { label: 'read_only', value: 'read_only' },
  { label: 'write_with_approval', value: 'write_with_approval' },
  { label: 'write_auto', value: 'write_auto' },
]

function emptyForm() {
  return {
    name: '', description: '', domain: '', permission: 'read_only',
    handler: { type: 'python', module: '', function: '', method: 'GET', url: '', auth_env: '', command: '', args: [] },
    handlerArgsStr: '',
    inputSchemaStr: '{"type":"object","properties":{},"required":[]}',
  }
}

const columns = [
  { title: '名称', key: 'name', width: 160 },
  { title: '描述', key: 'description', ellipsis: { tooltip: true } },
  { title: '类型', key: 'handler.type', width: 90 },
  { title: '权限', key: 'permission', width: 160 },
  { title: '领域', key: 'domain', width: 90 },
  {
    title: '操作', key: 'actions', width: 200,
    render(row) {
      return h(NSpace, { size: 'small' }, () => [
        h(NButton, { size: 'small', onClick: () => openTest(row.name) }, () => '测试'),
        h(NButton, { size: 'small', onClick: () => openEdit(row) }, () => '编辑'),
        h(NButton, { size: 'small', type: 'error', onClick: () => removeTool(row.name) }, () => '删除'),
      ])
    },
  },
]

async function load() {
  loading.value = true
  try {
    const data = await enterpriseToolsApi.list()
    tools.value = (data.tools || []).map(t => ({ ...t, 'handler.type': t.handler?.type }))
  } catch (e) {
    message.error('加载失败：' + (e.response?.data?.detail || e.message))
  }
  loading.value = false
}

function openCreate() {
  editName.value = ''
  form.value = emptyForm()
  showCreate.value = true
}

function openEdit(row) {
  editName.value = row.name
  form.value = {
    name: row.name, description: row.description, domain: row.domain || '', permission: row.permission,
    handler: { type: 'python', module: '', function: '', method: 'GET', url: '', auth_env: '', command: '', args: [], ...row.handler },
    handlerArgsStr: (row.handler?.args || []).join(','),
    inputSchemaStr: JSON.stringify(row.input_schema, null, 2),
  }
  showCreate.value = true
}

async function saveTool() {
  let input_schema
  try {
    input_schema = JSON.parse(form.value.inputSchemaStr)
  } catch {
    message.error('input_schema 不是合法 JSON')
    return
  }
  const handler = { ...form.value.handler }
  if (handler.type === 'cli') {
    handler.args = form.value.handlerArgsStr.split(',').map(s => s.trim()).filter(Boolean)
  }
  // 清理非本类型的字段，保持 YAML 干净
  saving.value = true
  try {
    const body = {
      name: form.value.name,
      description: form.value.description,
      input_schema,
      handler,
      permission: form.value.permission,
      domain: form.value.domain,
    }
    if (editName.value) {
      await enterpriseToolsApi.update(editName.value, body)
    } else {
      await enterpriseToolsApi.create(body)
    }
    message.success(editName.value ? '已更新' : '已导入')
    showCreate.value = false
    load()
  } catch (e) {
    message.error(e.response?.data?.detail || '保存失败')
  }
  saving.value = false
}

async function removeTool(name) {
  if (!confirm(`删除工具 ${name}？`)) return
  try {
    await enterpriseToolsApi.remove(name)
    message.success('已删除')
    load()
  } catch {
    message.error('删除失败')
  }
}

function openTest(name) {
  testName.value = name
  testArgsStr.value = '{}'
  testResult.value = ''
  showTest.value = true
}

async function runTest() {
  let args
  try {
    args = JSON.parse(testArgsStr.value)
  } catch {
    message.error('arguments 不是合法 JSON')
    return
  }
  testing.value = true
  testResult.value = '执行中...'
  try {
    const data = await enterpriseToolsApi.test(testName.value, { arguments: args })
    testResult.value = data.result
  } catch (e) {
    testResult.value = '错误：' + (e.response?.data?.detail || String(e))
  }
  testing.value = false
}

onMounted(load)
</script>

<style scoped>
.enterprise-tools { padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header h2 { margin: 0; }
</style>
