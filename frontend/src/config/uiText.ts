/**
 * 文案模板唯一真源（架构 §8.3）
 *
 * ## 为什么必须集中
 * 现状页面各自拼字符串：`showToast('请选择设备并填写计划名称')`（两个字段合成一句、
 * 3 秒消失、不定位）、`暂无数据`（四类空态混成一句）。UE §5.1 与 §8 给出了明确的
 * 文案口径，一旦散落就无法保证 21 个模块一致。
 *
 * ## 口径来源
 * - 空态四分类：UE §5.1「空」行（真无数据 / 筛选无结果 / 无权限或数据范围 / 加载失败）
 * - 错误文案格式：UE §8「空态/错误文案」行 —— `字段/对象 + 问题 + 怎么改`
 * - 危险操作：UE §5.1「危险操作」行 —— **禁止**"确定/取消"式无语义文案
 * - 回执：UE §2.5「完成必须可核对」—— 单号 + 关键数量 + 时间
 *
 * ## 硬规则
 * 1. 页面**不得**拼字符串，一律从这里取。
 * 2. 危险操作按钮文案必须是动作语义（`确认作废` / `再想想`），不是 `确定` / `取消`。
 * 3. 网络失败与业务失败**必须**是两套文案（UE §5.1 明确禁止混用）。
 */

/** 数量格式化：最多 3 位小数，去掉多余的 0（UE §8「数字与单位」） */
export function formatQty(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-'
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) return String(value)
  const fixed = num.toFixed(3)
  return fixed.replace(/\.?0+$/, '')
}

/**
 * 文案模板。
 *
 * 每个函数都只做"填空"，不做业务判断；业务判断留在页面。
 */
export const txt = {
  /**
   * 校验类。格式固定为 `字段 + 问题`（"怎么改"由输入提示承担）。
   * 例：`工序编码必填`、`周期值应在 1~365 之间`
   */
  validation: {
    required: (label: string): string => `${label}必填`,
    range: (label: string, lo: number | string, hi: number | string): string =>
      `${label}应在 ${lo}~${hi} 之间`,
    min: (label: string, lo: number | string): string => `${label}不应小于 ${lo}`,
    max: (label: string, hi: number | string): string => `${label}不应大于 ${hi}`,
    integer: (label: string): string => `${label}必须是整数`,
    decimals: (label: string, n: number): string => `${label}最多 ${n} 位小数`,
    pattern: (label: string, hint: string): string => `${label}格式不对，应为 ${hint}`,
    duplicate: (label: string, value: string): string => `${label}「${value}」已存在，请换一个`,
    notFound: (label: string, value: string): string => `没有找到${label}「${value}」，请核对后重试`,
    /** 顶部错误摘要（UE-10：必须给出"N 项待修正"并可点跳） */
    summary: (n: number): string => `${n} 项待修正`,
  },

  /**
   * 空态四分类（UE §5.1）。**禁止**统一成"暂无数据"。
   */
  empty: {
    /** ① 真无数据：说明 + 主操作 */
    true: (obj: string, action: string): string => `还没有${obj}，${action}开始第一条`,
    /** ② 筛选无结果：回显当前条件 + 清空 */
    filtered: (cond: string): string => `当前条件下没有${cond}`,
    filteredAction: (): string => '清空条件',
    /** ③ 无权限 / 无数据范围 */
    scoped: (scope: string): string => `当前仅显示${scope}的数据`,
    scopedHint: (): string => '如需查看更多，请联系管理员开通数据范围',
    /** ④ 加载失败 */
    failed: (): string => '加载失败',
    failedAction: (): string => '重试',
  },

  /**
   * 错误类。网络失败与业务失败必须是两套（UE §5.1 / UE-12）。
   */
  error: {
    /** 网络层失败：本次请求没发出去/没回来，不要提示"提交失败"（用户会重复提交） */
    network: (): string => '网络不可用，本次提交未发出',
    networkAction: (): string => '检查网络后重试',
    /** 服务端 5xx */
    server: (): string => '服务异常，请稍后重试或联系管理员',
    /** 业务失败：直接用后端 message（后端已写成"对象+问题+怎么改"） */
    business: (message: string): string => message,
    /** 403：缺权限，权限码要可复制给管理员（UE-14） */
    forbidden: (perm: string): string => `缺少权限 ${perm}`,
    forbiddenHint: (): string => '把这段权限码发给管理员开通后刷新即可',
    /** 401 会话过期 */
    sessionExpired: (): string => '登录已过期，请重新登录',
    /** 404 */
    notFound: (obj: string): string => `${obj}不存在或已被删除`,
    /** 校验整体失败 */
    invalid: (n: number): string => `有 ${n} 项内容需要修正，已定位到第一项`,
  },

  /**
   * 回执卡（UE §2.5 / UE-11）。结构必须含：单号 + 关键数量 + 时间。
   */
  receipt: {
    title: (action: string): string => `${action}成功`,
    /** 单号标签，值由页面给 */
    no: (label: string): string => `${label}`,
    /** 关键数量行，如 `合格数 120 PCS` */
    qty: (label: string, value: number | string, unit?: string): string =>
      unit ? `${label} ${formatQty(value)} ${unit}` : `${label} ${formatQty(value)}`,
    /** 时间行 */
    time: (iso: string): string => `提交时间 ${iso}`,
    /** 下一步：继续 / 查看 / 返回 */
    nextBuild: (obj: string): string => `继续新建${obj}`,
    nextView: (obj: string): string => `查看${obj}`,
    nextBack: (): string => '返回列表',
    /** 差异摘要（出库/发料场景） */
    diff: (lines: number, qty: string): string => `${lines} 行有差异，合计 ${qty}`,
  },

  /**
   * 危险操作（UE §5.1：必须重述后果与影响对象；按钮文案必须有语义）。
   * 默认焦点在"再想想"，且不与主操作同位置。
   */
  danger: {
    confirm: (obj: string, consequence: string): string => `确认作废 ${obj}？${consequence}`,
    confirmDelete: (obj: string): string => `确认删除 ${obj}？删除后不可恢复`,
    /** 中风险：明确按钮 */
    okLabel: (action: string): string => `确认${action}`,
    /** 取消一律用"再想想"，避免"取消"被误读为"取消操作"以外的含义 */
    cancelLabel: (): string => '再想想',
    /** 高风险：长按进度环 */
    holdHint: (ms: number): string => `按住不放 ${Math.round(ms / 1000)} 秒以确认`,
    /** 高风险：输入单据号后 4 位 */
    typeHint: (n: number): string => `请输入单据号后 ${n} 位以确认`,
  },

  /**
   * 离线 / 弱网（UE §5.1）。顶部常驻条，不遮挡操作区。
   */
  offline: {
    bar: (n: number): string => (n > 0 ? `离线 · ${n} 条待提交` : '离线 · 数据不会丢失'),
    queued: (n: number): string => `已存本地 ${n} 条，联网后请手动重试`,
    retry: (): string => '重试',
    discard: (): string => '删除待提交',
    /** 高风险操作在离线态必须拦住（UE §5.1 明确禁止） */
    blockedDanger: (): string => '离线状态下不能执行该操作，请联网后再试',
  },

  /**
   * 通用动作词。集中在这里是为了术语一致（Q5）。
   */
  action: {
    create: '新建',
    edit: '编辑',
    save: '保存',
    submit: '提交',
    search: '搜索',
    reset: '重置',
    advancedSearch: '高级检索',
    cancel: '再想想',
    close: '关闭',
    back: '返回',
    more: '更多',
    expand: '展开',
    collapse: '收起',
    remove: '删除',
    scan: '扫码',
    retry: '重试',
    refresh: '刷新',
  },

  /**
   * 执行页（T04 三条执行路径）专用文案。
   *
   * 集中在这里的原因：三条路径的"进度 / 差异 / 联动"措辞必须一致 ——
   * 同一个意思在检验页叫"已录"、在出库页叫"已发"、在点检页叫"已点"是可以的
   * （业务对象不同），但"还差几项""已生成安灯"这类**跨页复述**必须同口径，
   * 否则现场在三张单之间来回时会对不上号。
   */
  execute: {
    /** 扫码入口标题：说明"扫什么" */
    scanTitle: (obj: string, codes: string): string => `扫${obj}（${codes}）`,
    scanPlaceholder: (obj: string): string => `扫码或输入${obj}后回车`,
    /** 扫到了但当前对象里没有这个码 */
    scanNoMatch: (obj: string, code: string): string => `${obj}里没有「${code}」，请核对`,
    /** 扫到的单已经判定过：判定是终态，不能再进录入页改数 */
    alreadyJudged: (): string => '该单已判定，不能再录入（如需复检请新建检验单）',
    /** 定位单据这一步的主按钮（H 形态底部条 / W 形态行内都用它） */
    locateAction: (): string => '开始检验',

    /** 本单未挂标准（degraded）时的顶部说明 —— 不能假装清单是准的 */
    degradedBanner: (n: number): string =>
      `本单未关联检验标准，请先勾选本单适用的检验项（共 ${n} 项可选）`,
    degradedAction: (n: number): string => `确认适用项（已选 ${n} 项）`,
    selectAll: (): string => '全选',
    clearAll: (): string => '清空',
    selectedCount: (n: number, total: number): string => `已选 ${n} / ${total} 项`,
    needSelectAtLeastOne: (): string => '请至少勾选 1 个检验项才能开始录入',

    /** 逐项录入的进度 */
    progress: (done: number, total: number): string => `已录 ${done} / ${total} 项`,
    /** 某项缺录 */
    itemMissing: (name: string): string => `「${name}」还没录结论`,

    /** 数值与规格的实时提示（给"按下限自动判定"一个可解释的说法） */
    willPass: (): string => '按规格将判为合格',
    willFail: (): string => '按规格将判为不合格',
    specNone: (): string => '本项无上下限，需人工判合格/不合格',

    /** Ac/Re 建议判定 */
    verdictHint: (defect: number, ac: number, re: number, suggest: string): string =>
      `不合格 ${defect} 项 · Ac ${ac} / Re ${re} · 建议判定 ${suggest}`,
    verdictNoPlan: (): string => '本单未配置抽样方案，请人工判定',

    /** 已转 NCR（回执 extra 用，必须可点） */
    ncrRaised: (id: number): string => `已转 NCR #${id}`,
    andonRaised: (id: number): string => `已生成安灯 #${id}`,

    /** 出库：差额结案 */
    shortageLine: (lineNo: number, qty: string, unit: string): string =>
      `第 ${lineNo} 行欠 ${qty}${unit ? ' ' + unit : ''}`,
    shortageConsequence: (lines: number, detail: string): string =>
      `${lines} 行未发齐（${detail}），结案后不可补拣`,
    shortCloseAction: (): string => '差额结案',
    shortCloseOk: (): string => '结案',
    shortReason: (): string => '现场差额结案',
    /** 出库行状态 */
    lineDone: (): string => '已发',
    linePartial: (): string => '已发部分',
    linePending: (): string => '未发',
    /** 出库汇总 */
    issueSummary: (done: number, total: number): string => `已发完 ${done} / ${total} 行`,

    /** 点检 */
    taskNeedStart: (): string => '任务还没开工，开工后才能提交点检',
    taskStart: (): string => '开工',
    taskStarted: (status: string): string => `已开工，设备状态 ${status}`,
    checklistEmpty: (): string => '该任务还没有点检项',
    checklistEmptyHint: (): string => '可以先用标准点检项模板生成，再按现场增删',
    useTemplate: (): string => '使用标准点检项模板',
    addItem: (): string => '添加点检项',
    itemNamePlaceholder: (): string => '点检项目名，如「皮带张紧度」',
    /** 项级三态（与状态字典 maintenance_item 同口径，此处只给动作词） */
    verdictNormal: (): string => '正常',
    verdictAbnormal: (): string => '异常',
    verdictNa: (): string => '不适用',
    abnormalDesc: (): string => '异常描述',
    abnormalDescPlaceholder: (): string => '如：皮带打滑、有异响',
    photo: (): string => '拍照',
    photoCount: (n: number, max: number): string => `已拍 ${n} / ${max} 张`,
    photoLocalOnly: (): string =>
      '照片以压缩后的内联数据随单保存（后端暂无对象存储上传接口）',
    /** 点检回执 */
    checkedSummary: (checked: number, abnormal: number): string =>
      `${checked} 项已点检，${abnormal} 项异常`,
    submitConclude: (): string => '提交并完工',
    submitOnly: (): string => '仅保存点检',
    needVerdictAll: (): string => '还有点检项没有判定',
  },

  /** 状态提示（轻量、不改变数据、不改动单号，用 toast 即可） */
  toast: {
    saved: (obj: string): string => `${obj}已保存`,
    copied: (what: string): string => `${what}已复制`,
    draftKept: (): string => '草稿已保留，下次进入自动带出',
    draftCleared: (): string => '草稿已清除',
    submitting: (): string => '正在提交，请稍候',
    alreadySubmitted: (): string => '已提交，请勿重复操作',
  },
} as const

export type UiText = typeof txt
