/**
 * 知微 ziwi · 前端枚举单一真源
 *
 * 为什么要有这个文件：`OP_TYPE` 原本在 `OperationList.vue` 和 `searchFields.ts`
 * 各存了一份一模一样的 11 项常量，两处都漏了 `incoming_qc / process_qc /
 * final_qc` —— 而这三个值库里真有（艾华推进器场景的「定子电检（第一次）」
 * 就是 `process_qc`）。于是列表「工序类型」列直接印英文原文。
 *
 * 约定：前端所有枚举只准从这里取；后端真源是 `backend/app/core/enums.py`，
 * 两侧一致性由 `backend/app/tests/test_op_type_domain.py` 断言。
 */

export interface EnumOption {
  value: string
  label: string
}

/**
 * 工序类型。顺序与后端 `OP_TYPE_LABELS` 一致（dict 保持插入序）：
 * 先加工/装配类主类型，再把三种检验（来料/过程/终检）排在一起。
 */
export const OP_TYPE_OPTIONS: EnumOption[] = [
  { value: 'machining', label: '机加工' },
  { value: 'assembly', label: '装配' },
  { value: 'heat_treat', label: '热处理' },
  { value: 'surface_treat', label: '表面处理' },
  { value: 'inspect', label: '检验' },
  { value: 'incoming_qc', label: '来料检' },
  { value: 'process_qc', label: '过程检' },
  { value: 'final_qc', label: '终检' },
  { value: 'pack', label: '包装' },
  { value: 'reaction', label: '反应' },
  { value: 'blend', label: '混合' },
  { value: 'separation', label: '分离' },
  { value: 'filling', label: '灌装' },
  { value: 'transport', label: '转运' },
]

/**
 * 代码 → 中文标签。未知值给「未知（原文）」而不是回显原文。
 *
 * ⚠️ 兜底回显原文会让**脏数据看起来像正常值**：用户看到 `production`
 * 只会以为"这个系统就是显示英文的"，而不会想到库里存了个非法值。
 * `mfg_demo` 的 65 条探针工序正是这么藏了三轮没被发现。
 */
export function opTypeLabel(code: string | null | undefined): string {
  if (!code) return ''
  const hit = OP_TYPE_OPTIONS.find((o) => o.value === code)
  return hit ? hit.label : `未知（${code}）`
}

/**
 * 仓库类型（`warehouses.type`）。顺序与后端 `WAREHOUSE_TYPE_LABELS` 一致 ——
 * 物流方向：原料进厂 → 线边 → 在制/半成品 → 成品 → 备件/耗材。
 *
 * ⚠️ 这里原来有**两份**4 项硬编码：`WarehouseTree.vue::whTypeLabel` 和模型注释。
 * 库里实际有 7 个值（`raw`/`wip`/`finished_goods`/`line_side`/`spare_parts` 都在
 * 声明域之外），于是线边仓、备件仓在树上直接印英文原码。
 * 现在只剩这一份，由 `test_warehouse_type_domain.py` 与后端逐项同序对账。
 */
export const WAREHOUSE_TYPE_OPTIONS: EnumOption[] = [
  { value: 'raw_material', label: '原料仓' },
  { value: 'line_side', label: '线边仓' },
  { value: 'semi', label: '半成品仓' },
  { value: 'finished', label: '成品仓' },
  { value: 'spare_parts', label: '备件仓' },
  { value: 'consumable', label: '耗材仓' },
]

/**
 * 工作中心类别（`work_centers.wc_type`）。顺序与后端 `WC_TYPE_LABELS` 一致
 * （dict 插入序即下拉顺序），一致性由 `test_wc_type_domain.py` 断言。
 *
 * ★ 这个字段混了**两种正交语义**，是历史遗留，前端如实呈现：
 *   - 粒度：产线 / 工作单元 / 工位（`work_centers` 表本身就是这一层的单元）
 *   - 工艺性质：机加工 / 装配 / 热处理 / …（艾华 33 个工位全在这一维）
 *   拆成两个字段要先给 33 行数据归因（工位"是工位"还是"是装配"，两个答案都对），
 *   属产品决策，所以先把值域收到一处、加闸看住。
 *
 * ⚠️ 这里原来有**两份** 3 项副本（`WorkCenterList.vue::WC_TYPE_OPTIONS`
 *   和 `searchFields.ts::WC_TYPE`），都只抄了粒度三值，而库里实际是工艺性质
 *   → 列表「类型」列 33/33 行直接印英文 `assembly` / `quality` / `machining`。
 *   现在只剩这一份。
 */
export const WC_TYPE_OPTIONS: EnumOption[] = [
  // 粒度
  { value: 'production_line', label: '产线' },
  { value: 'work_cell', label: '工作单元' },
  { value: 'workstation', label: '工位' },
  // 工艺性质
  { value: 'machining', label: '机加工' },
  { value: 'assembly', label: '装配' },
  { value: 'heat_treat', label: '热处理' },
  { value: 'surface_treat', label: '表面处理' },
  { value: 'quality', label: '检验' },
  { value: 'pack', label: '包装' },
]

/**
 * 工作中心类别 → 中文。未知值给「未知（原文）」。
 *
 * 与 `opTypeLabel` 同一口径：**不允许 `|| v` 回退原文**（那个写法让脏值
 * 看起来像正常值，`mfg_demo` 的 65 条探针工序就这么藏了三轮）。
 */
export function wcTypeLabel(code: string | null | undefined): string {
  if (!code) return ''
  const hit = WC_TYPE_OPTIONS.find((o) => o.value === code)
  return hit ? hit.label : `未知（${code}）`
}

/**
 * 工艺性质 —— **从工序派生**的值域，不是工位档案里那个字段。
 *
 * 工位到底在干什么活，取决于它在工艺路线上承担的工序（`operations.op_type`），
 * 由后端每次现算，不落库。这里只负责把派生结果翻成中文。
 *
 * ★ 为什么单独一份、不复用 `WC_TYPE_OPTIONS`：
 *   后者是工作中心**档案字段**的写入值域（混了粒度与工艺性质），而工艺性质
 *   是 `op_type` 归一的结果（4 种检验 → quality）。曾经借用过一次，结果
 *   `filling`（灌装）在 wc_type 表里查不到 → 界面显示「未知（filling）」。
 *   后端真源 `core/enums.py::PROCESS_NATURE_LABELS`，两边逐项同序。
 */
export const PROCESS_NATURE_OPTIONS: EnumOption[] = [
  { value: 'machining', label: '机加工' },
  { value: 'assembly', label: '装配' },
  { value: 'heat_treat', label: '热处理' },
  { value: 'surface_treat', label: '表面处理' },
  { value: 'quality', label: '检验' },
  { value: 'pack', label: '包装' },
  { value: 'reaction', label: '反应' },
  { value: 'blend', label: '混合' },
  { value: 'separation', label: '分离' },
  { value: 'filling', label: '灌装' },
  { value: 'transport', label: '转运' },
]

/**
 * 工艺性质 → 中文。未知值给「未知（原文）」，**不允许 `|| v` 回退**。
 */
export function natureLabel(code: string | null | undefined): string {
  if (!code) return ''
  const hit = PROCESS_NATURE_OPTIONS.find((o) => o.value === code)
  return hit ? hit.label : `未知（${code}）`
}

/* ────────────────────────────────────────────────────────────
 * 非状态类枚举：类型 / 级别 / 来源 / 通道
 *
 * 为什么不并进 `statusDict.ts`：那张表带 `semantic`+`icon`，用于渲染带色标签；
 * 这里只是"码 → 中文"的纯文案，用在 `van-cell :value`、表格列这类地方。
 * 混在一起会让 `statusDict` 变成万能表，语义档定义迟早被稀释。
 *
 * ⚠️ `source_type` / `priority` 这类名字在**不同实体上值域不同**
 *   （NCR 的 source_type 是 iqc/process/fqc…，WMS 单据的是 po/wo/so…），
 *   所以一律按 domain 分开登记，不做"同名合并"。
 * ──────────────────────────────────────────────────────────── */

export const LABEL_DICT: Record<string, Record<string, string>> = {
  /** 检验单类型（M03）。实测 8 种，模型注释只写了 3 种 */
  inspection_type: {
    iqc: '来料检',
    ipqc: '过程检',
    fqc: '终检',
    oqc: '出货检',
    inspection: '常规检验',
    first: '首件检验',
    spot_check: '抽检',
    trial: '试制检验',
  },

  /** 入库单类型。★ 库里中英文混存：`purchase`/`production` 与 `生产入库` 并存 */
  receipt_type: {
    purchase: '采购入库',
    production: '生产入库',
    return: '退货入库',
    transfer: '调拨入库',
    生产入库: '生产入库',
    退货入库: '退货入库',
  },

  /** 出库单类型。★ 同样中英混存 */
  issue_type: {
    production: '生产领料',
    return: '退料入库',
    scrap: '报废出库',
    transfer: '调拨出库',
    销售出库: '销售出库',
  },

  /** 物料类型 ★ 文案取物料页的既有说法（消耗品/包装），避免同值两叫法 */
  material_type: {
    raw: '原材料',
    semi: '半成品',
    finished: '成品',
    consumable: '消耗品',
    package: '包装',
  },

  /** 产品类型 */
  product_type: {
    final: '成品',
    semi: '半成品',
    raw: '原材料',
  },

  /** 库位类型 ★ 库里实际出现 `normal` / `qc_hold` / `ng`，模型注释里都没有 */
  location_type: {
    shelf: '货架',
    floor: '地堆',
    cold: '冷藏',
    area: '区域',
    normal: '普通库位',
    qc_hold: '待检区',
    ng: '不良品区',
  },

  /** 工厂日历日类型 */
  day_type: {
    workday: '工作日',
    rest: '休息日',
    holiday: '法定假日',
    adjust_work: '调休上班',
    adjust_rest: '调休休息',
  },

  /** 安灯呼叫类型 ★ 并入了安灯页原有的 process/delivery 两值 */
  call_type: {
    quality: '质量',
    equipment: '设备',
    material: '物料',
    safety: '安全',
    personnel: '人员',
    process: '工艺',
    delivery: '交付',
    other: '其他',
  },

  /** NCR 来源 */
  ncr_source: {
    iqc: '来料检',
    ipqc: '过程检',
    fqc: '终检',
    spc: 'SPC 判异',
    process: '制程',
    trial: '试产',
    spot_check: '抽检',
    manual: '手工开单',
    customer: '客诉',
  },

  /** 单据来源（WMS / 通用） */
  doc_source: {
    po: '采购订单',
    wo: '工单',
    so: '销售订单',
    adjust: '库存调整',
    stock_move: '库内移库',
    purchase: '采购',
    production: '生产',
    return: '退货',
    transfer: '调拨',
  },

  /** SPC 控制图类型 */
  chart_type: {
    xbar_r: 'X̄-R 控制图',
    p: 'P 控制图',
    np: 'NP 控制图',
  },

  /** 库存预警类型 */
  alert_type: {
    min_stock: '低于最低库存',
    max_stock: '超出最高库存',
    safety_stock: '低于安全库存',
    slow_moving: '呆滞物料',
    expiry: '即将过期',
  },

  /** FMEA 类型 */
  fmea_type: {
    dfmea: 'DFMEA',
    pfmea: 'PFMEA',
    efmea: 'EFMEA',
  },

  /** 试产类型 ★ 列表页写「新产品」、详情页写「新产品试产」—— 统一取详情页的完整说法 */
  trial_type: {
    new_product: '新产品试产',
    new_process: '新工艺试产',
    new_material: '新材料试产',
    eco_verification: '工程变更验证',
    tooling_trial: '模具/工装验证',
  },

  /** 试产评审结论 */
  trial_conclusion: {
    pending: '待评审',
    approved: '通过',
    conditional_approve: '有条件通过',
    terminated: '终止',
    adjust: '需调整',
    rejected: '不通过',
  },

  /** 实验室委托类型 ★ 统一取详情页的完整说法（列表页原写「力学」、详情页写「力学性能」） */
  lab_request_type: {
    mechanical: '力学性能',
    metallographic: '金相分析',
    chemical: '化学成分',
    dimensional: '尺寸测量',
    environmental: '环境试验',
    physical: '物理性能',
    aging: '老化试验',
    ndt: '无损检测',
    cleanliness: '洁净度',
    other: '其他',
  },

  /** 实验结论 ★ 两个域并存：报告 pass/fail/conditional，单项 pass/fail/inconclusive */
  lab_conclusion: {
    pass: '通过',
    fail: '不通过',
    conditional: '有条件通过',
    inconclusive: '结论不明',
  },

  /** 优先级 ★ 库里用 `medium`，模型注释写 `normal` —— 两个都收 */
  priority: {
    low: '低',
    normal: '普通',
    medium: '中',
    high: '高',
    emergency: '紧急',
    urgent: '紧急',
  },

  /** 工艺路线类型 */
  route_type: {
    discrete: '离散制造',
    process: '流程制造',
  },

  /** 工单类型 */
  wo_type: {
    production: '生产',
    maintenance: '维修',
    rework: '返工',
    trial: '试产',
  },

  /** 能源类型 */
  energy_type: {
    electricity: '电',
    water: '水',
    gas: '气',
    heat: '热',
    steam: '蒸汽',
    compressed_air: '压缩空气',
  },

  /** 能源计量设备类型（M11） */
  energy_device_type: {
    electricity_meter: '电表',
    water_meter: '水表',
    gas_meter: '气表',
    heat_meter: '热量表',
    steam_meter: '蒸汽表',
  },

  /** 数据采集设备类型（M12）★ 与 energy_device_type 字段同名但值域不同，不能合并 */
  collect_device_type: {
    sensor: '传感器',
    actuator: '执行器',
    controller: '控制器',
    plc: 'PLC',
    instrument: '仪表',
    edge_gateway: '边缘网关',
    industrial_pc: '工控机',
    cloud_gateway: '云网关',
  },

  /** 拣货状态 */
  pick_status: {
    pending: '待拣货',
    picked: '已拣货',
  },

  /** 通用来源（自动/手工/物联） */
  source: {
    auto: '自动',
    manual: '手工',
    iot: '物联采集',
  },

  /**
   * 检验结果录入通道。
   * ★ 名字也撞了：`source` 在检验结果上是 `web/miniapp/device`，
   *   在安灯/通用场景上是 `auto/manual/iot` —— **同名不同域**，
   *   合并会出现"web 显示成自动"这种静默错译，只能分域存。
   */
  entry_source: {
    web: 'PC 录入',
    miniapp: '小程序',
    device: '设备直连',
  },

  /** NCR 处置方式 */
  disposition: {
    return: '退货',
    sorting: '挑选',
    concession: '让步接收',
    rework: '返工',
    scrap: '报废',
    claim: '索赔',
  },

  /** 通知通道 ★ 后端声明 board/broadcast/wechat/dingtalk/sms/email，
   *  而安灯升级规则页默认写 `app,message` —— 两套都收，否则列表直接印 `app,message` */
  notify_channel: {
    app: 'App 推送',
    message: '站内信',
    board: '看板显示',
    broadcast: '广播',
    wechat: '企业微信',
    dingtalk: '钉钉',
    sms: '短信',
    email: '邮件',
  },

  /** 通用模式 */
  mode: {
    auto: '自动',
    manual: '手动',
  },
}

/**
 * 仓库类型从 `WAREHOUSE_TYPE_OPTIONS` 推出来，**不在这里再写一遍**：
 * 写两遍就是两个真源，早晚有一份漏掉新值（这正是本次要修的病根）。
 * 登记进 `LABEL_DICT` 之后，页面统一走 `enumLabel('warehouse_type', …)`。
 */
LABEL_DICT.warehouse_type = Object.fromEntries(
  WAREHOUSE_TYPE_OPTIONS.map((o) => [o.value, o.label]),
)

/**
 * 码 → 中文。未知值给「未知（原码）」。
 *
 * 为什么未知必须带前缀：直接回显原文时，`normal` 这种库里有、注释里没有的值
 * 会被当成"正常显示"，于是没人去修数据。带「未知」前缀才逼出真问题。
 */
export function enumLabel(domain: string, code: string | null | undefined): string {
  if (code === null || code === undefined || code === '') return '-'
  const group = LABEL_DICT[domain]
  if (!group) return `未知（${code}）`
  return group[String(code)] ?? `未知（${code}）`
}

/** 某 domain 是否已登记（供静态闸/单测核对覆盖面） */
export function hasLabelDomain(domain: string): boolean {
  return Object.prototype.hasOwnProperty.call(LABEL_DICT, domain)
}

/**
 * domain → 下拉/标签组选项（`{ value, text }`，Vant 的 `DropdownItemOption` 形状）。
 *
 * 存在的理由：页面原先各自手写一份 `[{value:'first',text:'首件检验'}, …]`，
 * 于是"库里新增一个值 → 筛选项漏一个"永远靠人肉同步（`IssueOrderList` 就漏过
 * `return`、还写了个库里不存在的 `sales`）。从字典推出来就不会漂。
 */
export function enumOptions(domain: string): Array<{ value: string; text: string }> {
  const group = LABEL_DICT[domain]
  if (!group) return []
  return Object.entries(group).map(([value, text]) => ({ value, text }))
}

/**
 * 逗号分隔的多值枚举 → 中文顿号串。用于 `notify_channels` 这类"存 JSON/CSV"的列。
 *
 * 不传分隔符就按逗号切：后端把这列声明成「JSON 数组」，实际存的却是
 * `app,message` 这种裸 CSV —— 直接渲染会原样印到界面上。
 */
export function enumListLabel(
  domain: string,
  csv: string | null | undefined,
  sep = ',',
): string {
  if (!csv) return '-'
  const parts = String(csv)
    .split(sep)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!parts.length) return '-'
  return parts.map((c) => enumLabel(domain, c)).join('、')
}
