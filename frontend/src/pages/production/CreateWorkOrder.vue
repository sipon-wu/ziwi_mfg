<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import { errMessage } from '@/utils/error'

const router = useRouter()
const form = ref({ wo_no: '', product_code: '', product_name: '', planned_qty: 0, remark: '' })
const submitting = ref(false)

/* ── 默认路线预览 ──────────────────────────────────────────────
 * 这个表单**没有选路线的入口**（历史上就没有），路线靠后端按"产品默认
 * 路线"回填。不把这件事显示出来的话，用户建完单在详情里看到一条自己没选
 * 过的路线，只会以为是系统乱填的 —— 或者反过来，没有路线时不知道为什么。
 * 这里只做「预览 + 说明」，真正的回填仍在后端（唯一真源）。
 * ──────────────────────────────────────────────────────────── */
const routeHint = ref('')
const routeHintWarn = ref(false)
let hintSeq = 0

async function previewRoute() {
  routeHint.value = ''
  routeHintWarn.value = false
  const code = (form.value.product_code || '').trim()
  if (!code) return
  const seq = ++hintSeq
  try {
    const res: any = await get('/products', { params: { keyword: code, page: 1, page_size: 10 } })
    const hit = (res?.items || []).find((p: any) => p.code === code)
    if (!hit || seq !== hintSeq) return
    const r: any = await get(`/products/${hit.id}/routes`)
    if (seq !== hintSeq) return
    // 生效期由后端算（effective_now），前端不重复实现这条规则
    const d = (r?.items || []).find((x: any) => x.is_default && x.effective_now)
    if (d) {
      routeHint.value = `将自动关联默认路线「${d.route_name}」`
    } else {
      routeHint.value = '该产品没有生效中的默认路线，建单不会自动带路线（报工无法按工序归集）'
      routeHintWarn.value = true
    }
  } catch {
    // 预览失败不影响建单：回填是后端做的，这里纯提示
    routeHint.value = ''
  }
}

async function handleSubmit() {
  submitting.value = true
  try {
    // 后端现在回 { id, wo_no }。建完直接进详情，省掉
    // "回列表 → 搜索 → 点进去"这套动作。
    const res: any = await post('/work-orders', form.value)
    // 后端会回 route_auto（按产品默认路线自动关联的那条）与 warnings
    // （无 BOM、未挂工艺、草稿工艺…）。这些必须让用户看见 ——
    // 吞掉的话"为什么带了路线/为什么没带"全靠猜。
    const warns: string[] = res?.warnings || []
    if (warns.length) showToast(warns[0])
    else if (res?.route_auto) showToast(`已自动关联默认路线「${res.route_auto.route_name}」`)
    else showToast('创建成功')
    if (res?.id) router.replace(`/work-orders/${res.id}`)
    else router.push('/work-orders')
  } catch (e: any) {
    // 以前这里固定弹"创建失败"，把"工单号已存在，请换一个单号"这类
    // 后端人话全吞了 —— 用户只能猜自己哪儿填错了。
    showToast(errMessage(e, '创建失败'))
  } finally { submitting.value = false }
}
</script>

<template>
  <div>
    <van-nav-bar title="新建工单" left-arrow @click-left="router.back()" />
    <van-form @submit="handleSubmit" style="margin-top:16px">
      <van-field v-model="form.wo_no" label="工单号" placeholder="自动生成或手动输入" :rules="[{required:true}]" />
      <van-field v-model="form.product_code" label="产品编码" :rules="[{required:true}]"
                 @blur="previewRoute" />
      <div v-if="routeHint" class="route-hint" :class="{ 'is-warn': routeHintWarn }">
        {{ routeHint }}
      </div>
      <van-field v-model="form.product_name" label="产品名称" :rules="[{required:true}]" />
      <van-field v-model.number="form.planned_qty" label="计划数量" type="digit" :rules="[{required:true}]" />
      <van-field v-model="form.remark" label="备注" type="textarea" rows="3" />
      <div style="margin:16px"><van-button round block type="primary" native-type="submit" :loading="submitting">提交</van-button></div>
    </van-form>
  </div>
</template>

<style scoped>
/* 默认路线提示：正常是安静的说明，没有默认路线时用警示色 ——
   "没带路线"会让报工无法按工序归集，属于会被忽略但影响口径的状态 */
.route-hint {
  font-size: 12px;
  line-height: 1.5;
  margin: 0 16px 8px 16px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #eef7ee;
  color: #2e7d32;
}
.route-hint.is-warn { background: #fff7e6; color: #b26a00; }
</style>
