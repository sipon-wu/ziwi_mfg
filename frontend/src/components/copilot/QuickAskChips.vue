<template>
  <div class="quick-chips">
    <span
      v-for="q in questions"
      :key="q"
      class="chip"
      @click="emit('ask', q)"
    >
      {{ q }}
    </span>
  </div>
</template>

<script setup lang="ts">
const emit = defineEmits<{ (e: 'ask', question: string): void }>()

const questions: string[] = [
  '昨天产量是多少',
  '今天各产线良率',
  '本月工单按期交付率',
  '现在在制工单有多少',
  '本月不良TOP3',
  '今天有哪些安灯未响应',
  '设备状态分布',
  '今天产量良率OEE汇总',
]
</script>

<style scoped>
.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 12px;
}
.chip {
  font-size: 12px;
  color: var(--ziwi-primary);
  background: var(--ziwi-primary-bg);
  border-radius: 14px;
  padding: 4px 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.chip:hover {
  background: #d5ebe6;
}
</style>
