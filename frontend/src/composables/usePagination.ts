import { ref, type Ref } from 'vue'

export interface PaginationState {
  page: Ref<number>
  pageSize: Ref<number>
  total: Ref<number>
  loading: Ref<boolean>
}

export interface UsePaginationReturn extends PaginationState {
  /**
   * 上一次拉取是否失败。
   *
   * 为什么必须暴露：`fetchPage` 一直是 try/finally、**没有 catch**，请求失败时
   * `loading` 归位、列表仍是空的，页面就渲染成「暂无数据」——车间看到的是
   * "没有数据"，而不是"没拉到数据"，于是重复建单/重复报工。
   *
   * 错误照旧向上抛（调用方原有的 try/catch 不受影响），这里只额外记一个标志。
   */
  loadFailed: Ref<boolean>
  fetchPage: (
    fetchFn: (params: { page: number; page_size: number }) => Promise<{ total?: number; items?: unknown[] }>,
  ) => Promise<unknown[]>
  resetPage: () => void
}

export function usePagination(defaultPageSize = 20): UsePaginationReturn {
  const page = ref(1)
  const pageSize = ref(defaultPageSize)
  const total = ref(0)
  const loading = ref(false)
  const loadFailed = ref(false)

  async function fetchPage(
    fetchFn: (params: { page: number; page_size: number }) => Promise<{ total?: number; items?: unknown[] }>,
  ): Promise<unknown[]> {
    loading.value = true
    loadFailed.value = false
    try {
      const res = await fetchFn({ page: page.value, page_size: pageSize.value })
      total.value = res.total ?? 0
      return res.items ?? []
    } catch (error) {
      loadFailed.value = true
      throw error
    } finally {
      loading.value = false
    }
  }

  function resetPage(): void {
    page.value = 1
    total.value = 0
  }

  return { page, pageSize, total, loading, loadFailed, fetchPage, resetPage }
}
