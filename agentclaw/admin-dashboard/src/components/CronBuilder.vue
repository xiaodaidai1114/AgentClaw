<template>
  <div class="cron-builder">
    <!-- 频率选择 -->
    <div class="form-group">
      <label>{{ t('cronBuilder.frequency') }}</label>
      <select v-model="frequency" @change="onFrequencyChange">
        <option v-for="option in frequencyOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
    </div>

    <!-- 每周：星期选择 -->
    <div v-if="frequency === 'weekly'" class="form-group">
      <label>{{ t('cronBuilder.weekday') }}</label>
      <div class="weekday-picker">
        <label v-for="day in weekdays" :key="day.value" class="weekday-option" :class="{ checked: selectedDays.includes(day.value) }">
          <input type="checkbox" :value="day.value" v-model="selectedDays" @change="updateCron">
          <span>{{ day.label }}</span>
        </label>
      </div>
      <div class="form-hint" v-if="selectedDays.length === 0" style="color: var(--error)">{{ t('cronBuilder.selectAtLeastOneDay') }}</div>
    </div>

    <!-- 每月：日历选择 -->
    <div v-if="frequency === 'monthly'" class="form-group">
      <label>{{ t('cronBuilder.date') }} <span class="form-hint-inline">({{ t('cronBuilder.monthlyRepeatHint') }})</span></label>
      <div class="calendar-view">
        <!-- 月份导航 -->
        <div class="calendar-nav">
          <button type="button" class="cal-nav-btn" @click="prevMonth">&lt;</button>
          <span class="cal-nav-title">{{ calendarTitle }}</span>
          <button type="button" class="cal-nav-btn" @click="nextMonth">&gt;</button>
        </div>
        <!-- 星期标题 -->
        <div class="calendar-header">
          <div v-for="day in calendarWeekdays" :key="day" class="calendar-weekday">{{ day }}</div>
        </div>
        <!-- 日期网格 -->
        <div class="calendar-grid">
          <!-- 前置空白 -->
          <div v-for="n in firstDayOfMonth" :key="'pad-' + n" class="calendar-day placeholder"></div>
          <!-- 实际日期 -->
          <label
            v-for="day in daysInMonth"
            :key="day"
            class="calendar-day"
            :class="{
              checked: selectedMonthDays.includes(day),
              today: isToday(day),
              overflow: day > 28
            }"
          >
            <input type="checkbox" :value="day" v-model="selectedMonthDays" @change="updateCron">
            <span>{{ day }}</span>
          </label>
        </div>
        <!-- 提示：29-31 号不是每月都有 -->
        <div v-if="hasOverflowDays" class="calendar-overflow-hint">
          * {{ overflowHint }}
        </div>
      </div>
      <div class="form-hint" v-if="selectedMonthDays.length === 0" style="color: var(--error)">{{ t('cronBuilder.selectAtLeastOneDay') }}</div>
    </div>

    <!-- 时间选择 -->
    <div v-if="frequency !== 'custom'" class="form-group">
      <label>{{ t('cronBuilder.time') }}</label>
      <div class="time-picker">
        <input type="number" v-model.number="hour" @input="updateCron" min="0" max="23" :placeholder="t('cronBuilder.hourPlaceholder')">
        <span class="time-separator">:</span>
        <input type="number" v-model.number="minute" @input="updateCron" min="0" max="59" :placeholder="t('cronBuilder.minutePlaceholder')">
      </div>
      <div class="form-hint">{{ t('cronBuilder.timeFormatHint') }}</div>
    </div>

    <!-- 自定义表达式 -->
    <div v-if="frequency === 'custom'" class="form-group">
      <label>{{ t('cronBuilder.expression') }}</label>
      <input type="text" v-model="customExpression" @input="onCustomExpressionChange" :placeholder="t('cronBuilder.customPlaceholder')" style="font-family: monospace">
      <div class="form-hint">
        {{ t('cronBuilder.expressionFormat') }}
        <a href="https://crontab.guru/" target="_blank" style="margin-left: 8px">{{ t('cronBuilder.referenceDocs') }}</a>
      </div>
    </div>

    <!-- 预览 -->
    <div class="cron-preview">
      <div class="preview-label">{{ t('cronBuilder.preview') }}</div>
      <div class="preview-content">
        <div class="preview-description">{{ description }}</div>
        <code class="preview-expression">{{ expression }}</code>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  modelValue: {
    type: String,
    default: '0 9 * * *'
  }
})

const emit = defineEmits(['update:modelValue'])
const { t, locale } = useI18n()

// 频率选项
const frequency = ref('daily')
const frequencyOptions = computed(() => ([
  { label: t('cronBuilder.frequencies.daily'), value: 'daily' },
  { label: t('cronBuilder.frequencies.weekly'), value: 'weekly' },
  { label: t('cronBuilder.frequencies.monthly'), value: 'monthly' },
  { label: t('cronBuilder.frequencies.custom'), value: 'custom' },
]))

// 星期选择（0=周日, 1=周一...6=周六）
const weekdays = computed(() => ([
  { label: t('cronBuilder.weekdays.monday'), value: 1 },
  { label: t('cronBuilder.weekdays.tuesday'), value: 2 },
  { label: t('cronBuilder.weekdays.wednesday'), value: 3 },
  { label: t('cronBuilder.weekdays.thursday'), value: 4 },
  { label: t('cronBuilder.weekdays.friday'), value: 5 },
  { label: t('cronBuilder.weekdays.saturday'), value: 6 },
  { label: t('cronBuilder.weekdays.sunday'), value: 0 },
]))
const calendarWeekdays = computed(() => ([
  t('cronBuilder.calendarWeekdays.sunday'),
  t('cronBuilder.calendarWeekdays.monday'),
  t('cronBuilder.calendarWeekdays.tuesday'),
  t('cronBuilder.calendarWeekdays.wednesday'),
  t('cronBuilder.calendarWeekdays.thursday'),
  t('cronBuilder.calendarWeekdays.friday'),
  t('cronBuilder.calendarWeekdays.saturday'),
]))
const selectedDays = ref([1]) // 默认周一

// 每月日期选择
const selectedMonthDays = ref([1]) // 默认1号

// 日历导航
const now = new Date()
const calendarYear = ref(now.getFullYear())
const calendarMonth = ref(now.getMonth()) // 0-indexed
const calendarTitle = computed(() => new Date(calendarYear.value, calendarMonth.value, 1).toLocaleDateString(locale.value || undefined, {
  year: 'numeric',
  month: 'long',
}))

// 当前月第一天是星期几（0=周日）
const firstDayOfMonth = computed(() => {
  return new Date(calendarYear.value, calendarMonth.value, 1).getDay()
})

// 当前月天数
const daysInMonth = computed(() => {
  return new Date(calendarYear.value, calendarMonth.value + 1, 0).getDate()
})

// 判断是否是今天
function isToday(day) {
  const today = new Date()
  return calendarYear.value === today.getFullYear()
    && calendarMonth.value === today.getMonth()
    && day === today.getDate()
}

// 切换月份
function prevMonth() {
  if (calendarMonth.value === 0) {
    calendarMonth.value = 11
    calendarYear.value--
  } else {
    calendarMonth.value--
  }
}

function nextMonth() {
  if (calendarMonth.value === 11) {
    calendarMonth.value = 0
    calendarYear.value++
  } else {
    calendarMonth.value++
  }
}

// 检查是否选了 29/30/31
const hasOverflowDays = computed(() => {
  return selectedMonthDays.value.some(d => d > 28)
})

const overflowHint = computed(() => {
  const days = selectedMonthDays.value.filter(d => d > 28).sort((a, b) => a - b)
  if (days.length === 0) return ''
  const hints = []
  if (days.includes(31)) hints.push(t('cronBuilder.overflow.day31'))
  if (days.includes(30)) hints.push(t('cronBuilder.overflow.day30'))
  if (days.includes(29)) hints.push(t('cronBuilder.overflow.day29'))
  return hints.join('; ')
})

// 时间
const hour = ref(9)
const minute = ref(0)

// 自定义表达式
const customExpression = ref('')

// 生成的 cron 表达式
const expression = computed(() => {
  if (frequency.value === 'custom') {
    return customExpression.value
  }

  const m = minute.value
  const h = hour.value

  if (frequency.value === 'daily') {
    return `${m} ${h} * * *`
  }

  if (frequency.value === 'weekly') {
    if (selectedDays.value.length === 0) return `${m} ${h} * * *`
    const days = [...selectedDays.value].sort((a, b) => a - b).join(',')
    return `${m} ${h} * * ${days}`
  }

  if (frequency.value === 'monthly') {
    if (selectedMonthDays.value.length === 0) return `${m} ${h} * * *`
    const days = [...selectedMonthDays.value].sort((a, b) => a - b).join(',')
    return `${m} ${h} ${days} * *`
  }

  return `${m} ${h} * * *`
})

// 描述文本
const description = computed(() => {
  if (frequency.value === 'custom') {
    return parseCronDescription(customExpression.value)
  }

  const timeStr = `${String(hour.value).padStart(2, '0')}:${String(minute.value).padStart(2, '0')}`

  if (frequency.value === 'daily') {
    return t('cronBuilder.description.daily', { time: timeStr })
  }

  if (frequency.value === 'weekly') {
    if (selectedDays.value.length === 0) return t('cronBuilder.description.selectWeekday')
    const dayLabels = [...selectedDays.value]
      .sort((a, b) => a - b)
      .map(v => weekdays.value.find(d => d.value === v)?.label)
      .filter(Boolean)
      .join(', ')
    return t('cronBuilder.description.weekly', { days: dayLabels, time: timeStr })
  }

  if (frequency.value === 'monthly') {
    if (selectedMonthDays.value.length === 0) return t('cronBuilder.description.selectDate')
    const dayStr = [...selectedMonthDays.value].sort((a, b) => a - b).join(', ')
    return t('cronBuilder.description.monthly', { days: dayStr, time: timeStr })
  }

  return ''
})

// 更新 cron 表达式
function updateCron() {
  emit('update:modelValue', expression.value)
}

// 频率变化
function onFrequencyChange() {
  if (frequency.value === 'custom') {
    customExpression.value = expression.value
  }
  updateCron()
}

// 自定义表达式变化
function onCustomExpressionChange() {
  emit('update:modelValue', customExpression.value)
}

// 解析 cron 表达式为描述（简单实现）
function parseCronDescription(expr) {
  if (!expr || !expr.trim()) return t('cronBuilder.parse.enterExpression')

  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return t('cronBuilder.parse.invalidFormat')

  const [m, h, dom, , dow] = parts

  if (dow !== '*' && dom === '*') {
    return t('cronBuilder.parse.specificWeekly', { hour: h, minute: m })
  }
  if (dom !== '*' && dow === '*') {
    return t('cronBuilder.parse.specificMonthly', { hour: h, minute: m })
  }
  if (dom === '*' && dow === '*') {
    return t('cronBuilder.parse.daily', { hour: h, minute: m })
  }

  return t('cronBuilder.parse.raw', { expr })
}

// 初始化：解析传入的 cron 表达式
function parseCronExpression(expr) {
  if (!expr || !expr.trim()) return

  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) {
    frequency.value = 'custom'
    customExpression.value = expr
    return
  }

  const [m, h, dom, mon, dow] = parts

  minute.value = m === '*' ? 0 : parseInt(m) || 0
  hour.value = h === '*' ? 9 : parseInt(h) || 9

  // 每天
  if (dom === '*' && mon === '*' && dow === '*') {
    frequency.value = 'daily'
    return
  }

  // 每周
  if (dom === '*' && mon === '*' && dow !== '*') {
    frequency.value = 'weekly'
    if (dow.includes(',')) {
      selectedDays.value = dow.split(',').map(d => parseInt(d)).filter(d => !isNaN(d))
    } else if (dow.includes('-')) {
      const [start, end] = dow.split('-').map(d => parseInt(d))
      selectedDays.value = []
      for (let i = start; i <= end; i++) {
        selectedDays.value.push(i)
      }
    } else {
      selectedDays.value = [parseInt(dow)]
    }
    return
  }

  // 每月
  if (dom !== '*' && mon === '*' && dow === '*') {
    frequency.value = 'monthly'
    if (dom.includes(',')) {
      selectedMonthDays.value = dom.split(',').map(d => parseInt(d)).filter(d => !isNaN(d))
    } else {
      selectedMonthDays.value = [parseInt(dom)]
    }
    return
  }

  // 其他情况视为自定义
  frequency.value = 'custom'
  customExpression.value = expr
}

// 监听外部变化
watch(() => props.modelValue, (newVal) => {
  if (newVal !== expression.value) {
    parseCronExpression(newVal)
  }
}, { immediate: true })

// 监听内部变化
watch(expression, (newVal) => {
  emit('update:modelValue', newVal)
})
</script>

<style scoped>
.cron-builder {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-hint-inline {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 400;
}

/* 星期选择器 */
.weekday-picker {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.weekday-option {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
}

.weekday-option input[type="checkbox"] {
  display: none;
}

.weekday-option:hover {
  border-color: var(--primary);
  background: var(--primary-light);
}

.weekday-option.checked {
  border-color: var(--primary);
  background: var(--primary);
  color: white;
}

/* 日历视图 */
.calendar-view {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  background: white;
}

.calendar-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.cal-nav-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  width: 28px;
  height: 28px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.cal-nav-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.cal-nav-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.calendar-header {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  margin-bottom: 4px;
}

.calendar-weekday {
  text-align: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  padding: 4px 0;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.calendar-day {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  font-size: 13px;
  background: white;
  position: relative;
}

.calendar-day.placeholder {
  border: none;
  cursor: default;
}

.calendar-day input[type="checkbox"] {
  display: none;
}

.calendar-day:not(.placeholder):hover {
  border-color: var(--primary);
  background: var(--primary-light);
}

.calendar-day.checked {
  border-color: var(--primary);
  background: var(--primary);
  color: white;
  font-weight: 500;
}

.calendar-day.today:not(.checked) {
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

.calendar-day.overflow:not(.checked) {
  color: var(--text-secondary);
}

.calendar-overflow-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--warning);
  line-height: 1.5;
}

/* 时间选择器 */
.time-picker {
  display: flex;
  align-items: center;
  gap: 8px;
}

.time-picker input[type="number"] {
  width: 70px;
  text-align: center;
  font-size: 16px;
  font-weight: 500;
}

.time-separator {
  font-size: 18px;
  font-weight: 500;
  color: var(--text-secondary);
}

/* 预览 */
.cron-preview {
  background: var(--bg-light);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 14px;
}

.preview-label {
  font-size: 11px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.preview-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-description {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.preview-expression {
  font-size: 12px;
  color: var(--text-secondary);
  background: white;
  padding: 6px 10px;
  border-radius: 4px;
  border: 1px solid var(--border);
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
}
</style>
