<template>
  <div class="feedback-bar">
    <span class="fb-label">这个回答有帮助吗？</span>
    <button
      class="fb-btn"
      :class="{ active: chosen === 'good' }"
      :disabled="disabled || !!chosen"
      @click="pick('good')"
    >
      👍
    </button>
    <button
      class="fb-btn"
      :class="{ active: chosen === 'bad' }"
      :disabled="disabled || !!chosen"
      @click="pick('bad')"
    >
      👎
    </button>
    <span v-if="chosen" class="fb-thanks">谢谢反馈</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ (e: 'feedback', rating: 'good' | 'bad'): void }>()

const chosen = ref<'' | 'good' | 'bad'>('')

function pick(rating: 'good' | 'bad') {
  if (chosen.value || props.disabled) return
  chosen.value = rating
  emit('feedback', rating)
}
</script>

<style scoped>
.feedback-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--ziwi-text-muted);
}
.fb-btn {
  border: 1px solid var(--ziwi-border);
  background: var(--ziwi-bg-white);
  border-radius: var(--ziwi-radius-sm);
  padding: 2px 8px;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.4;
}
.fb-btn:hover:not(:disabled) {
  border-color: var(--ziwi-primary);
}
.fb-btn.active {
  border-color: var(--ziwi-primary);
  background: var(--ziwi-primary-bg);
}
.fb-btn:disabled {
  cursor: default;
  opacity: 0.7;
}
.fb-thanks {
  color: var(--ziwi-success);
}
</style>
