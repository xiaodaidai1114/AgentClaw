import { ref, watch, onMounted } from 'vue'

/**
 * 列表页通用逻辑：分页、搜索、loading、数据拉取
 * @param {Function} fetchFn - 异步获取数据函数，接收 { page, limit, search } 参数，返回 { items, total }
 * @param {Object} options - 可选配置 { pageSize: 20, immediate: true }
 */
export function useList(fetchFn, options = {}) {
  const page = ref(1)
  const pageSize = ref(options.pageSize ?? 20)
  const total = ref(0)
  const items = ref([])
  const loading = ref(false)
  const searchQuery = ref('')

  async function fetchData() {
    loading.value = true
    try {
      const result = await fetchFn({
        page: page.value,
        limit: pageSize.value,
        search: searchQuery.value
      })
      items.value = result.items
      total.value = result.total
    } catch (e) {
      console.error(e)
    } finally {
      loading.value = false
    }
  }

  function handlePageChange(newPage) {
    page.value = newPage
    fetchData()
  }

  function handlePageSizeChange(newSize) {
    pageSize.value = newSize
    page.value = 1
    fetchData()
  }

  // 搜索防抖
  let timer
  watch(searchQuery, () => {
    clearTimeout(timer)
    timer = setTimeout(() => { page.value = 1; fetchData() }, 300)
  })

  if (options.immediate !== false) {
    onMounted(fetchData)
  }

  return {
    page, pageSize, total, items, loading, searchQuery,
    fetchData, handlePageChange, handlePageSizeChange
  }
}
