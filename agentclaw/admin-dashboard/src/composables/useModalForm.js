import { ref, reactive } from 'vue'

/**
 * 模态框表单状态管理
 * @param {Function} defaultValues - 返回表单默认值的工厂函数
 */
export function useModalForm(defaultValues) {
  const visible = ref(false)
  const isEdit = ref(false)
  const form = reactive({ ...defaultValues() })

  function openCreate() {
    Object.assign(form, defaultValues())
    isEdit.value = false
    visible.value = true
  }

  function openEdit(item) {
    Object.assign(form, item)
    isEdit.value = true
    visible.value = true
  }

  function close() {
    visible.value = false
  }

  return { visible, isEdit, form, openCreate, openEdit, close }
}
