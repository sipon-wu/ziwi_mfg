<script setup lang="ts">
/**
 * ZiwiListToolbar — 列表页统一工具栏（查询组 / 操作组）
 *
 * ## 为什么有这个组件
 * 表格型列表页（工序/工作中心/产品/工艺路线）各自复制了一段工具栏，同一个毛病
 * 抄了四遍：搜索框 `flex-1` 拉满整行，搜索按钮被推到四百多像素之外，中间还夹着
 * 筛选下拉。输入完要横跨半个屏幕找提交键。
 *
 * ## 结构约束（本组件替页面守住，页面不用再各写各的）
 * 1. **搜索紧贴输入框**：输入框有宽度上限（`--ziwi-list-input-max`），搜索按钮与它
 *    同属一个 flex 单元、间距 `--ziwi-touch-gap-adj`，永远不会被推开；
 * 2. **条件在输入之前**：筛选下拉走 `#filters` 插槽，渲染在输入框左侧；
 * 3. **查询延伸紧邻清空**：高级检索紧跟重置，属查询组；
 * 4. **操作组独立靠右**：`#actions` 插槽用 `margin-left:auto` 推到最右，与查询组
 *    之间由弹性空白分隔，创建类动作不再插在查询控件中间；
 * 5. **同排同高**：组内按钮与输入框统一 48px（`--ziwi-touch-min`），不用
 *    `size="small"` 之类的档位，避免"大小档不一致"的观感。
 *
 * ## 次级动作不用白底描边
 * 重置 / 高级检索是**文字按钮**（`.ziwi-btn-text`：无边框、无底色）。原先它们是
 * 白底 + 1px `#dcdee0` 边框，而工具栏底色是 `#f0f2f5` —— 两种浅灰几乎同色，
 * 边框看不见，白块"飘"在实色按钮旁边，读起来像高度不齐。去掉描边后视觉重量
 * 天然分层：实色 = 主操作，纯文字 = 次操作。
 *
 * 依据：UE §6.3（同组相邻可点元素间距）、R3（一语义一组按钮）、
 *       `docs/ue-interaction-spec-2026-11-02.md`。
 */
const keyword = defineModel<string>('keyword', { default: '' })

withDefaults(
  defineProps<{
    /** 搜索框占位符 */
    placeholder?: string
    /** 是否显示「高级检索」入口 */
    showAdvanced?: boolean
    /** 搜索中（按钮转圈，防重复提交） */
    loading?: boolean
  }>(),
  {
    placeholder: '搜索关键词',
    showAdvanced: true,
    loading: false,
  },
)

const emit = defineEmits<{
  search: []
  reset: []
  advanced: []
}>()
</script>

<template>
  <div class="ziwi-list-toolbar">
    <div class="ziwi-list-toolbar__query">
      <!-- 条件：筛选下拉等，渲染在输入框之前 -->
      <slot name="filters" />

      <!-- 输入 + 提交：同一 flex 单元，搜索按钮不可能被推开 -->
      <div class="ziwi-list-toolbar__input">
        <van-field
          v-model="keyword"
          :placeholder="placeholder"
          clearable
          @keyup.enter="emit('search')"
        />
        <van-button type="primary" :loading="loading" @click="emit('search')">搜索</van-button>
      </div>

      <van-button class="ziwi-btn-text" @click="emit('reset')">重置</van-button>
      <van-button
        v-if="showAdvanced"
        class="ziwi-btn-text"
        icon="filter-o"
        @click="emit('advanced')"
      >高级检索</van-button>
    </div>

    <!-- 操作组：创建/导入/导出等，靠最右 -->
    <div class="ziwi-list-toolbar__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.ziwi-list-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ziwi-touch-gap-adj);
}

.ziwi-list-toolbar__query {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ziwi-touch-gap-adj);
  flex: 1 1 auto;
  min-width: 0;
}

/* 输入框宽度上限：不拉满整行，搜索按钮就不会被推到屏幕另一端。
   min-width 保证窄屏（H 档）下输入框仍可输入，按钮靠 flex 换行。 */
.ziwi-list-toolbar__input {
  display: flex;
  align-items: center;
  gap: var(--ziwi-touch-gap-adj);
  flex: 0 1 var(--ziwi-list-input-max, 360px);
  min-width: 220px;
}

.ziwi-list-toolbar__input :deep(.van-field) {
  /* 必须撑满输入单元，否则按钮会被 flex-basis 的剩余空间推离输入框 ——
     这正是原来「搜索按钮离开搜索框」的成因，不能在新组件里重演。 */
  flex: 1 1 auto;
  min-width: 0;
  min-height: var(--ziwi-touch-min);
  border: 1px solid var(--ziwi-state-neutral-bd);
  border-radius: var(--ziwi-radius-lg);
  background: var(--van-white, #fff);
}

/* 同排同高：不依赖调用方传 size，杜绝档位混用 */
.ziwi-list-toolbar :deep(.van-button) {
  height: var(--ziwi-touch-min);
  min-width: var(--ziwi-touch-min);
  padding-left: var(--ziwi-gap-md);
  padding-right: var(--ziwi-gap-md);
  font-size: var(--ziwi-font-size-md);
  /* 2 个汉字的按钮在 48px 宽度内会折成竖排「搜/索」——
     实测过，所以必须禁折行，让它按内容撑宽而不是换行。 */
  white-space: nowrap;
}

.ziwi-list-toolbar__actions {
  display: flex;
  gap: var(--ziwi-touch-gap-adj);
  margin-left: auto;
}

/* 条件插槽里的字段（下拉/附加输入框）也要 48px —— 插槽内容不受 scoped 影响，
   必须用 :slotted 才能命中。漏了这条，附加输入框会停在 Vant 默认 44px，
   又变成"同排不同高"。 */
.ziwi-list-toolbar :slotted(.van-field) {
  min-height: var(--ziwi-touch-min);
}

.ziwi-list-toolbar :slotted(.ziwi-list-toolbar__cond) {
  flex: 0 1 144px;
  min-width: 120px;
}

/* 次级动作：纯文字，无边框无底色（理由见文件头注释） */
.ziwi-list-toolbar :deep(.ziwi-btn-text) {
  border: none;
  background: transparent;
  color: var(--van-primary-color);
}

.ziwi-list-toolbar :deep(.ziwi-btn-text)::before {
  display: none;
}
</style>
