<template>
  <svg :viewBox="`0 0 ${W} ${H}`" class="w-full h-auto" preserveAspectRatio="none">
    <polyline
      v-for="(s, i) in normalized"
      :key="i"
      :points="s.points"
      :stroke="s.color"
      fill="none"
      stroke-width="2"
      stroke-linejoin="round"
      stroke-linecap="round"
      vector-effect="non-scaling-stroke"
    />
  </svg>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps({
  // [{ color: string, values: number[] }]
  series: { type: Array as () => { color: string; values: number[] }[], required: true },
  W: { type: Number, default: 300 },
  H: { type: Number, default: 100 },
});

const max = computed(() => {
  const nums = props.series.flatMap((s) => s.values.map((v) => (Number.isFinite(v) ? v : 0)));
  return Math.max(1, ...nums);
});

function points(values: number[]): string {
  if (!values.length) return "";
  const step = props.W / Math.max(values.length - 1, 1);
  const pad = props.H * 0.08;
  return values
    .map((v, i) => {
      const n = Number.isFinite(v) ? v : 0;
      const x = (i * step).toFixed(1);
      const y = (props.H - (n / max.value) * (props.H - pad * 2) - pad).toFixed(1);
      return `${x},${y}`;
    })
    .join(" ");
}

const normalized = computed(() =>
  props.series.map((s) => ({ color: s.color, points: points(s.values) }))
);
</script>
