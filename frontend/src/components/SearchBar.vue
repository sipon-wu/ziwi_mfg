<script setup lang="ts">
const keyword = defineModel<string>('keyword', { default: '' })
const emit = defineEmits<{
  search: [keyword: string]
}>()

function onSearch(val: string): void {
  emit('search', val)
}
</script>

<template>
  <van-search
    v-model="keyword"
    placeholder="搜索关键词"
    @search="onSearch"
  />
</template>
