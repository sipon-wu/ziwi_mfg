import { ref, type Ref } from 'vue'

export interface PaginationState {
  page: Ref<number>
  pageSize: Ref<number>
  total: Ref<number>
  loading: Ref<boolean>
}

export interface UsePaginationReturn extends PaginationState {
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

  async function fetchPage(
    fetchFn: (params: { page: number; page_size: number }) => Promise<{ total?: number; items?: unknown[] }>,
  ): Promise<unknown[]> {
    loading.value = true
    try {
      const res = await fetchFn({ page: page.value, page_size: pageSize.value })
      total.value = res.total ?? 0
      return res.items ?? []
    } finally {
      loading.value = false
    }
  }

  function resetPage(): void {
    page.value = 1
    total.value = 0
  }

  return { page, pageSize, total, loading, fetchPage, resetPage }
}
