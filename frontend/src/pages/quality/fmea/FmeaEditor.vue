<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put } from '@/api/client'
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'

interface TreeNode {
  id: number | null
  parent_id: number | null
  level_type: string | null
  sort_order: number
  label: string
  // 关联工序（→ operations.id）。PFMEA 发布时靠这个外键把高风险节点落到
  // operations.is_critical，不再按节点名称去猜工序（两套词表对不上）。
  operation_id: number | null
  children?: TreeNode[]
}

interface OperationOpt {
  id: number
  code: string
  name: string
  is_critical: boolean
}

interface FmeaItem {
  id: number
  doc_id: number
  hierarchy_id: number
  function_desc: string
  failure_mode: string
  failure_effect: string
  failure_cause: string
  current_control_prevent: string | null
  current_control_detect: string | null
  severity: number
  occurrence: number
  detection: number
  rpn: number
  is_high_risk: boolean
  is_critical_process: boolean
  recommended_action: string | null
  status: string
  created_at: string
  updated_at: string
}

interface DocInfo {
  id: number
  title: string
  doc_no: string
  fmea_type: string
  rpn_threshold: number
}

const route = useRoute()
const router = useRouter()
const docId = Number(route.params.id)
const docInfo = ref<DocInfo | null>(null)
const loading = ref(false)
const treeNodes = ref<TreeNode[]>([])
const fmeaItems = ref<FmeaItem[]>([])
const activeTab = ref<'structure' | 'matrix'>('structure')

// Structure tree editing
const editNodeLabel = ref('')
const editNodeLevelType = ref('system')
const editNodeOperationId = ref<string | number | null>(0)
const showAddNodeDialog = ref(false)
const selectedParentId = ref<number | null>(null)
const addingNodeParentId = ref<number | null>(null)

// 关联工序
const operations = ref<OperationOpt[]>([])
const operationOptions = computed(() =>
  operations.value.map((o) => ({
    value: o.id,
    label: `${o.code} ${o.name}${o.is_critical ? '（关键）' : ''}`,
  })),
)
const showLinkOpDialog = ref(false)
const linkingNode = ref<TreeNode | null>(null)
const linkingOpId = ref<string | number | null>(0)
/* 下拉里显式放一个 0 = 「不关联」的哨兵项。不能靠"清空"表达解绑 ——
   SelectField 清空后回传的是 undefined，而整树覆盖保存会把 undefined 序列化成
   缺字段，后端拿到的就是 null，看着对、但用户无法区分"没选"和"故意解绑"。 */
const linkOperationOptions = computed(() => [
  { value: 0, label: '（不关联）' },
  ...operationOptions.value,
])

// FMEA item editing
const showItemDialog = ref(false)
const editingItem = ref<FmeaItem | null>(null)
const itemForm = ref({
  hierarchy_id: 0,
  function_desc: '',
  failure_mode: '',
  failure_effect: '',
  failure_cause: '',
  current_control_prevent: '',
  current_control_detect: '',
  severity: 5,
  occurrence: 4,
  detection: 4,
  is_critical_process: false,
  recommended_action: '',
})
const submitting = ref(false)

const levelTypeOptions = [
  { value: 'system', label: '系统' },
  { value: 'subsystem', label: '子系统' },
  { value: 'component', label: '零部件' },
  { value: 'process', label: '工序' },
  { value: 'operation', label: '工步' },
]

// 结构树保存：整棵覆盖
/* ⚠️ 后端 save_structure_tree 是 `delete_by_doc_id` + 逐条重插，不是按 id 更新。
   所以**每次提交都必须把 operation_id 带上** —— 漏字段不会报错，但整棵树的
   工序关联会被静默清空，表现为"刚关联好的工序，添加/删除一个节点后就没了"。
   三处调用统一走 saveTree，不要再各自拼 payload。 */
function treePayload(nodes: TreeNode[]) {
  return nodes.map((n) => ({
    id: n.id,
    parent_id: n.parent_id,
    label: n.label,
    level_type: n.level_type,
    sort_order: n.sort_order,
    operation_id: n.operation_id ?? null,
  }))
}

async function saveTree(nodes: TreeNode[]) {
  await post(`/fmea/documents/${docId}/tree`, { nodes: treePayload(nodes) })
}

function nodeSubtitle(node: TreeNode): string {
  const base = '类型: ' + (node.level_type || '-')
  if (!node.operation_id) return base + ' ｜ 关联工序: 未关联（点此行关联）'
  const op = operations.value.find((o) => o.id === node.operation_id)
  return base + ' ｜ 关联工序: ' + (op ? `${op.code} ${op.name}` : `#${node.operation_id}`)
}

function openLinkOp(node: TreeNode) {
  linkingNode.value = node
  linkingOpId.value = node.operation_id ?? 0
  showLinkOpDialog.value = true
}

async function handleSaveLinkOp() {
  const node = linkingNode.value
  if (!node) return
  const nextOpId = Number(linkingOpId.value) || null
  submitting.value = true
  try {
    const all = flattenTree(treeNodes.value).map((n) =>
      n.id === node.id ? { ...n, operation_id: nextOpId } : n,
    )
    await saveTree(all)
    showToast(nextOpId ? '已关联工序' : '已解除关联')
    showLinkOpDialog.value = false
    fetchData()
  } catch {
    showToast('保存失败')
  } finally {
    submitting.value = false
  }
}

async function fetchOperations() {
  try {
    const res = await get<{ items: OperationOpt[] }>('/operations', {
      params: { page: 1, page_size: 200 },
    })
    operations.value = res.items || []
  } catch {
    // 工序主数据拉不到不影响结构树编辑，只是关联下拉为空 —— 不打断页面
    operations.value = []
  }
}

async function fetchData() {
  loading.value = true
  try {
    docInfo.value = await get<DocInfo>(`/fmea/documents/${docId}`)
    const nodes = await get<TreeNode[]>(`/fmea/documents/${docId}/tree`)
    treeNodes.value = buildTree(nodes)

    const itemsRes = await get<{ items: FmeaItem[]; total: number }>('/fmea/items', { doc_id: docId, page_size: 100 })
    fmeaItems.value = itemsRes.items || []
  } catch (e) {
    showToast('加载FMEA数据失败')
    console.warn('[FmeaEditor]', e)
  } finally {
    loading.value = false
  }
}

function buildTree(nodes: TreeNode[]): TreeNode[] {
  const map = new Map<number | null, TreeNode[]>()
  const roots: TreeNode[] = []

  for (const node of nodes) {
    node.children = []
    const pid = node.parent_id
    if (!map.has(pid)) map.set(pid, [])
    map.get(pid)!.push(node)
  }

  for (const node of nodes) {
    node.children = map.get(node.id) || []
    if (node.parent_id === null) roots.push(node)
  }

  return roots
}

function flattenTree(nodes: TreeNode[]): TreeNode[] {
  const result: TreeNode[] = []
  function walk(list: TreeNode[]) {
    for (const n of list) {
      result.push(n)
      if (n.children) walk(n.children)
    }
  }
  walk(nodes)
  return result
}

function openAddNode(parentId: number | null) {
  addingNodeParentId.value = parentId
  editNodeLabel.value = ''
  editNodeLevelType.value = 'component'
  editNodeOperationId.value = 0
  showAddNodeDialog.value = true
}

async function handleAddNode() {
  if (!editNodeLabel.value) {
    showToast('请输入节点名称')
    return
  }
  submitting.value = true
  try {
    const allNodes = flattenTree(treeNodes.value)
    const newNode: TreeNode = {
      id: null,
      parent_id: addingNodeParentId.value,
      label: editNodeLabel.value,
      level_type: editNodeLevelType.value,
      sort_order: allNodes.length + 1,
      operation_id: Number(editNodeOperationId.value) || null,
    }

    await saveTree([...allNodes, newNode])

    showToast('节点已添加')
    showAddNodeDialog.value = false
    fetchData()
  } catch {
    showToast('添加失败')
  } finally {
    submitting.value = false
  }
}

async function handleDeleteNode(nodeId: number) {
  try {
    await showConfirmDialog({ message: '确定删除该节点及其子节点？' })
    const remaining = flattenTree(treeNodes.value).filter(n => n.id !== nodeId)
    await saveTree(remaining)
    showToast('节点已删除')
    fetchData()
  } catch {
    // cancelled
  }
}

// FMEA item methods
function openAddItem(nodeId: number) {
  editingItem.value = null
  itemForm.value = {
    hierarchy_id: nodeId,
    function_desc: '',
    failure_mode: '',
    failure_effect: '',
    failure_cause: '',
    current_control_prevent: '',
    current_control_detect: '',
    severity: 5,
    occurrence: 4,
    detection: 4,
    is_critical_process: false,
    recommended_action: '',
  }
  showItemDialog.value = true
}

function openEditItem(item: FmeaItem) {
  editingItem.value = item
  itemForm.value = {
    hierarchy_id: item.hierarchy_id,
    function_desc: item.function_desc,
    failure_mode: item.failure_mode,
    failure_effect: item.failure_effect,
    failure_cause: item.failure_cause,
    current_control_prevent: item.current_control_prevent || '',
    current_control_detect: item.current_control_detect || '',
    severity: item.severity,
    occurrence: item.occurrence,
    detection: item.detection,
    is_critical_process: item.is_critical_process,
    recommended_action: item.recommended_action || '',
  }
  showItemDialog.value = true
}

function openNewItemDialog() {
  editingItem.value = null
  itemForm.value = {
    hierarchy_id: 0,
    function_desc: '',
    failure_mode: '',
    failure_effect: '',
    failure_cause: '',
    current_control_prevent: '',
    current_control_detect: '',
    severity: 5,
    occurrence: 4,
    detection: 4,
    is_critical_process: false,
    recommended_action: '',
  }
  showItemDialog.value = true
}

const computedRpn = () => itemForm.value.severity * itemForm.value.occurrence * itemForm.value.detection

async function handleSaveItem() {
  if (!itemForm.value.function_desc) {
    showToast('请填写功能描述')
    return
  }
  submitting.value = true
  try {
    if (editingItem.value) {
      await put(`/fmea/items/${editingItem.value.id}`, itemForm.value)
      showToast('更新成功')
    } else {
      await post('/fmea/items', {
        ...itemForm.value,
        doc_id: docId,
      })
      showToast('创建成功')
    }
    showItemDialog.value = false
    fetchData()
  } catch {
    showToast(editingItem.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

function getRpnLevel(rpn: number): string {
  const threshold = docInfo.value?.rpn_threshold || 100
  if (rpn >= threshold) return 'high'
  if (rpn >= threshold * 0.7) return 'medium'
  return 'low'
}

onMounted(() => {
  fetchData()
  fetchOperations()
})
</script>

<template>
  <div>
    <van-nav-bar :title="docInfo ? docInfo.title : 'FMEA编辑'" left-arrow @click-left="router.back()">
      <template #right>
        <van-button size="mini" plain type="primary" @click="fetchData">刷新</van-button>
      </template>
    </van-nav-bar>

    <van-loading v-if="loading" />

    <div v-else>
      <!-- Tab切换 -->
      <van-tabs v-model:active="activeTab">
        <van-tab title="结构树" name="structure">
          <div style="margin:8px; display:flex; gap:8px; flex-wrap:wrap;">
            <van-button size="small" type="primary" @click="openAddNode(null)">添加根节点</van-button>
          </div>

          <!-- 递归渲染结构树 -->
          <div v-if="treeNodes.length">
            <template v-for="(node, nidx) in treeNodes" :key="'n' + (node.id ?? nidx)">
              <van-cell :title="node.label" :label="nodeSubtitle(node)" is-link @click="openLinkOp(node)">
                <template #value>
                  <van-button size="mini" plain type="primary" @click.stop="openAddNode(node.id)">添加子节点</van-button>
                  <van-button size="mini" plain type="danger" @click.stop="handleDeleteNode(node.id!)">删除</van-button>
                </template>
              </van-cell>
              <!-- Level 2 -->
              <div v-for="(child, cidx) in node.children" :key="'c' + (child.id ?? cidx)" style="margin-left:24px; border-left:2px solid #e8eaed; padding-left:8px;">
                <van-cell :title="child.label" :label="nodeSubtitle(child)" is-link @click="openLinkOp(child)">
                  <template #value>
                    <van-button size="mini" plain type="primary" @click.stop="openAddNode(child.id)">添加</van-button>
                    <van-button size="mini" plain type="danger" @click.stop="handleDeleteNode(child.id!)">删除</van-button>
                  </template>
                </van-cell>
                <!-- Level 3 -->
                <div v-for="(grandchild, gidx) in child.children" :key="'g' + (grandchild.id ?? gidx)" style="margin-left:24px; border-left:2px solid #e8eaed; padding-left:8px;">
                  <van-cell :title="grandchild.label" :label="nodeSubtitle(grandchild)" is-link @click="openLinkOp(grandchild)">
                    <template #value>
                      <van-button size="mini" plain type="danger" @click.stop="handleDeleteNode(grandchild.id!)">删除</van-button>
                    </template>
                  </van-cell>
                  <!-- Level 4 -->
                  <div v-for="(great, g2idx) in grandchild.children" :key="'x' + (great.id ?? g2idx)" style="margin-left:24px; border-left:2px solid #e8eaed; padding-left:8px;">
                    <van-cell :title="great.label" :label="nodeSubtitle(great)" is-link @click="openLinkOp(great)">
                      <template #value>
                        <van-button size="mini" plain type="danger" @click.stop="handleDeleteNode(great.id!)">删除</van-button>
                      </template>
                    </van-cell>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <ZiwiStateView
      state="empty-true"
      object-name="结构树"
      hint="点下方按钮添加根节点"
    />
        </van-tab>

        <van-tab title="FMEA项矩阵" name="matrix">
          <div style="margin:8px">
            <van-button size="small" type="primary" @click="openNewItemDialog()">新增FMEA项</van-button>
          </div>

          <van-list>
            <van-cell v-for="item in fmeaItems" :key="item.id"
              :style="item.is_high_risk ? 'background:#fff3f3' : ''">
              <template #title>
                <span>{{ item.function_desc }}</span>
                <van-tag
                  :type="getRpnLevel(item.rpn) === 'high' ? 'danger' : getRpnLevel(item.rpn) === 'medium' ? 'warning' : 'default'"
                  style="margin-left:6px"
                >RPN={{ item.rpn }}</van-tag>
              </template>
              <template #label>
                <div>失效模式: {{ item.failure_mode }}</div>
                <div>影响: {{ item.failure_effect }} | 原因: {{ item.failure_cause }}</div>
                <div>S={{ item.severity }} O={{ item.occurrence }} D={{ item.detection }}</div>
                <div v-if="item.recommended_action">建议措施: {{ item.recommended_action }}</div>
              </template>
              <template #value>
                <van-button size="mini" plain type="primary" @click="openEditItem(item)">编辑</van-button>
              </template>
            </van-cell>
          </van-list>
          <ZiwiStateView
      v-if="!fmeaItems.length"
      state="empty-true"
      object-name="FMEA项"
    />
        </van-tab>
      </van-tabs>
    </div>

    <!-- 添加节点弹窗 -->
    <ZiwiFormSheet v-model:show="showAddNodeDialog" title="添加节点" submit-text="保存" @submit="handleAddNode">
      <div style="padding:16px">
        <van-field v-model="editNodeLabel" label="节点名称" placeholder="必填" :rules="[{ required: true }]" />
        <van-field name="level_type" label="层级类型">
          <template #input>
            <van-radio-group v-model="editNodeLevelType" direction="horizontal">
              <van-radio v-for="t in levelTypeOptions" :key="t.value" :name="t.value">{{ t.label }}</van-radio>
            </van-radio-group>
          </template>
        </van-field>
        <van-field label="关联工序">
          <template #input>
            <SelectField v-model="editNodeOperationId" :options="linkOperationOptions" class="ziwi-w-full" />
          </template>
        </van-field>
        <div class="fmea-link-hint">
          只有关联了工序的节点，才会在 PFMEA 发布时把高风险标记写到工序主数据的「关键工序」上。
          不关联则发布时跳过该节点（会如实提示跳过数量）。
        </div>
      </div>
    </ZiwiFormSheet>

    <!-- 关联工序弹窗 -->
    <ZiwiFormSheet
      v-model:show="showLinkOpDialog"
      :title="linkingNode ? `关联工序 · ${linkingNode.label}` : '关联工序'"
      :submitting="submitting"
      submit-text="保存"
      @submit="handleSaveLinkOp"
    >
      <div style="padding:16px">
        <van-field label="工序">
          <template #input>
            <SelectField v-model="linkingOpId" :options="linkOperationOptions" class="ziwi-w-full" />
          </template>
        </van-field>
        <div class="fmea-link-hint">
          当选「（不关联）」时，该节点在 PFMEA 发布时不会产生任何关键工序标记。
        </div>
      </div>
    </ZiwiFormSheet>

    <!-- FMEA项编辑弹窗 -->
    <ZiwiFormSheet v-model:show="showItemDialog" :title="editingItem ? '编辑FMEA项' : '新增FMEA项'" submit-text="保存" @submit="handleSaveItem">
      <div style="padding:16px; max-height:400px; overflow-y:auto;">
        <van-field v-model="itemForm.function_desc" label="功能描述" type="textarea" rows="2" placeholder="必填" :rules="[{ required: true }]" />
        <van-field v-model="itemForm.failure_mode" label="失效模式" type="textarea" rows="1" placeholder="必填" />
        <van-field v-model="itemForm.failure_effect" label="失效影响" type="textarea" rows="1" />
        <van-field v-model="itemForm.failure_cause" label="失效原因" type="textarea" rows="1" />
        <van-field v-model="itemForm.current_control_prevent" label="预防控制" placeholder="选填" />
        <van-field v-model="itemForm.current_control_detect" label="探测控制" placeholder="选填" />
        <van-field v-model.number="itemForm.severity" label="严重度(S)" type="digit" placeholder="1-10" />
        <van-field v-model.number="itemForm.occurrence" label="频度(O)" type="digit" placeholder="1-10" />
        <van-field v-model.number="itemForm.detection" label="探测度(D)" type="digit" placeholder="1-10" />
        <van-cell title="RPN (自动计算)" :value="computedRpn()" />
        <van-field name="is_critical_process" label="关键工序(写回)">
          <template #input>
            <van-switch v-model="itemForm.is_critical_process" />
          </template>
        </van-field>
        <van-field v-model="itemForm.recommended_action" label="建议措施" type="textarea" rows="2" placeholder="选填" />
      </div>
    </ZiwiFormSheet>
  </div>
</template>

<style scoped>
/* 关联工序的说明文案：放在表单里而不是 tooltip —— 移动端 tooltip 点不到，
   而这段是"为什么发布了没标记"的唯一解释位。 */
.fmea-link-hint {
  padding: 8px 16px 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ziwi-text-secondary, #64748b);
}
</style>
