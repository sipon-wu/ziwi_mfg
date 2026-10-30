import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { matchPermission } from '@/stores/auth'

/* ── 生产管理模块路由的角色要求 ── */
const R_PROD = ['admin', 'department_head', 'team_leader', 'scheduler', 'process_engineer', 'key_user']
const R_SCHEDULE = ['admin', 'scheduler', 'department_head']
const R_BOMS = ['admin', 'process_engineer', 'department_head']

/* ── 设备管理 ── */
const R_EQUIP = ['admin', 'department_head', 'maintenance_tech', 'team_leader']

/* ── 品质管理 ── */
const R_QUALITY = ['admin', 'department_head', 'inspector', 'quality_engineer', 'key_user']
const R_SPC = ['admin', 'quality_engineer']
const R_PPAP = ['admin', 'quality_engineer']
const R_FMEA = ['admin', 'quality_engineer', 'process_engineer']

/* ── 其他模块 ── */
const R_ENERGY = ['admin', 'department_head', 'key_user']
const R_DC = ['admin', 'department_head', 'key_user']
const R_SYSTEM = ['admin', 'key_user']
const R_TRIAL = ['admin', 'process_engineer', 'department_head']

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'Login', component: () => import('@/pages/auth/Login.vue') },
  { path: '/403', name: 'Forbidden', component: () => import('@/pages/Forbidden.vue'), meta: { title: '无访问权限' } },
  { path: '/setup', name: 'SolutionConfig', component: () => import('@/pages/setup/SolutionConfig.vue'), meta: { title: '方案配置' } },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/pages/Dashboard.vue') },
      { path: 'workshop', name: 'WorkshopScreen', component: () => import('@/pages/dashboard/WorkshopScreen.vue') },
      { path: 'cockpit', name: 'Cockpit', component: () => import('@/pages/dashboard/Cockpit.vue') },
      // M01 - 生产管理
      { path: 'work-orders', name: 'WorkOrders', component: () => import('@/pages/production/WorkOrderList.vue'), meta: { perm: 'M01:work_order:read' } },
      { path: 'work-orders/create', name: 'CreateWorkOrder', component: () => import('@/pages/production/CreateWorkOrder.vue'), meta: { perm: 'M01:work_order:read' } },
      { path: 'work-orders/:id', name: 'WorkOrderDetail', component: () => import('@/pages/production/WorkOrderDetail.vue'), meta: { perm: 'M01:work_order:read' } },
      { path: 'work-reports', name: 'WorkReports', component: () => import('@/pages/production/WorkReportList.vue'), meta: { perm: 'M01:work_order:read' } },
      { path: 'work-reports/create', name: 'CreateReport', component: () => import('@/pages/production/WorkReportForm.vue'), meta: { perm: 'M01:work_order:read' } },
      { path: 'reports', name: 'Reports', component: () => import('@/pages/production/ReportView.vue'), meta: { perm: 'M01:work_order:read' } },
      { path: 'schedule', name: 'Schedule', component: () => import('@/pages/production/ScheduleGantt.vue'), meta: { title: '生产排产', perm: 'M01:work_order:read' } },
      // M02 - BOM管理
      { path: 'boms', name: 'BomList', component: () => import('@/pages/production/BomList.vue'), meta: { title: 'BOM管理', perm: 'M02:bom:read' } },
      // M04 - 工序定义
      { path: 'basics/operations', name: 'OperationList', component: () => import('@/pages/basics/OperationList.vue'), meta: { perm: 'M00:operation:read', title: '工序定义' } },
      // M05 - 工作中心
      { path: 'basics/work-centers', name: 'WorkCenterList', component: () => import('@/pages/basics/WorkCenterList.vue'), meta: { perm: 'M00:work_center:read', title: '工作中心' } },
      // M03 - 工艺路线
      { path: 'basics/routes', name: 'RouteList', component: () => import('@/pages/basics/RouteList.vue'), meta: { perm: 'M00:route:read', title: '工艺路线' } },
      { path: 'basics/route-editor/:id', name: 'RouteEditor', component: () => import('@/pages/basics/RouteEditor.vue'), meta: { perm: 'M00:route:read', title: '工序编排' } },
      // M01 - 产品管理
      { path: 'basics/products', name: 'ProductList', component: () => import('@/pages/basics/ProductList.vue'), meta: { perm: 'M00:product:read', title: '产品管理' } },
      // M06 - 工厂日历
      { path: 'basics/calendar', name: 'CalendarView', component: () => import('@/pages/basics/CalendarView.vue'), meta: { perm: 'M00:calendar:read', title: '工厂日历' } },
      // TPM 设备管理
      { path: 'equipment', name: 'Equipment', component: () => import('@/pages/equipment/EquipmentList.vue'), meta: { title: '设备管理', perm: 'M06:equipment:read' } },
      { path: 'equipment/create', name: 'CreateEquipment', component: () => import('@/pages/equipment/EquipmentCreate.vue'), meta: { title: '新增设备', perm: 'M06:equipment:read' } },
      { path: 'equipment/:id', name: 'EquipmentDetail', component: () => import('@/pages/equipment/EquipmentDetail.vue'), meta: { title: '设备详情', perm: 'M06:equipment:read' } },
      { path: 'equipment/maintenance-tasks', name: 'MaintenanceTasks', component: () => import('@/pages/equipment/MaintenanceTasks.vue'), meta: { title: '保养任务', perm: 'M06:equipment:read' } },
      { path: 'equipment/maintenance-plans', name: 'MaintenancePlans', component: () => import('@/pages/equipment/MaintenancePlans.vue'), meta: { title: '维护计划', perm: 'M06:equipment:read' } },
      // M05 - 安灯管理
      { path: 'andon', name: 'Andon', component: () => import('@/pages/andon/AndonList.vue'), meta: { perm: 'M05:andon_call:read', title: '安灯管理' } },
      { path: 'andon/:id', name: 'AndonDetail', component: () => import('@/pages/andon/AndonDetail.vue'), meta: { perm: 'M05:andon_call:read', title: '安灯详情' } },
      // M11 - 升级规则配置
      { path: 'andon/escalation-rules', name: 'EscalationRules', component: () => import('@/pages/andon/EscalationRules.vue'), meta: { title: '升级规则配置', perm: 'M05:andon_escalation_rule:read' } },
      // M03 - 品质管理
      { path: 'quality', name: 'Quality', component: () => import('@/pages/quality/InspectionList.vue'), meta: { title: '品质管理', perm: 'M03:inspection_order:read' } },
      { path: 'quality/create', name: 'CreateInspection', component: () => import('@/pages/quality/InspectionCreate.vue'), meta: { title: '新建检验', perm: 'M03:inspection_order:read' } },
      { path: 'quality/:id', name: 'QualityDetail', component: () => import('@/pages/quality/InspectionDetail.vue'), meta: { title: '检验详情', perm: 'M03:inspection_order:read' } },
      // NCR 是独立模块码 M30（列表页调 /ncr），拿 M03 的检验单只读码代替会让
      // "能看检验单但没 M30"的角色进去即 403（key_user 实测）。
      { path: 'quality/ncr', name: 'NcrList', component: () => import('@/pages/quality/NcrList.vue'), meta: { title: '不合格品评审', perm: 'M30:ncr:read' } },
      // SPC 统计分析
      { path: 'quality/spc/control-limits', name: 'SpcControlLimits', component: () => import('@/pages/quality/spc/ControlLimitList.vue'), meta: { title: 'SPC控制限配置', perm: 'M10:spc_control_limit:read' } },
      { path: 'quality/spc/control-limits/:id/chart', name: 'SpcControlChart', component: () => import('@/pages/quality/spc/ControlChart.vue'), meta: { title: 'SPC控制图', perm: 'M10:spc_control_limit:read' } },
      { path: 'quality/spc/control-limits/:id/capability', name: 'SpcCapability', component: () => import('@/pages/quality/spc/CapabilityAnalysis.vue'), meta: { title: '过程能力分析', perm: 'M10:spc_control_limit:read' } },
      // PPAP
      { path: 'quality/ppap/levels', name: 'PpapLevels', component: () => import('@/pages/quality/ppap/PpapLevels.vue'), meta: { title: 'PPAP等级配置', perm: 'M10:ppap_submission:read' } },
      { path: 'quality/ppap/submissions', name: 'PpapSubmissions', component: () => import('@/pages/quality/ppap/PpapSubmissions.vue'), meta: { title: 'PPAP提交管理', perm: 'M10:ppap_submission:read' } },
      { path: 'quality/ppap/elements', name: 'PpapElements', component: () => import('@/pages/quality/ppap/PpapElements.vue'), meta: { title: 'PPAP要素模板', perm: 'M10:ppap_submission:read' } },
      // FMEA
      { path: 'quality/fmea', name: 'FmeaList', component: () => import('@/pages/quality/fmea/FmeaList.vue'), meta: { title: 'FMEA管理', perm: 'M10:fmea_document:read' } },
      { path: 'quality/fmea/:id/edit', name: 'FmeaEditor', component: () => import('@/pages/quality/fmea/FmeaEditor.vue'), meta: { title: 'FMEA编辑', perm: 'M10:fmea_document:read' } },
      { path: 'quality/fmea/:id/actions', name: 'FmeaActions', component: () => import('@/pages/quality/fmea/FmeaActions.vue'), meta: { title: 'FMEA整改措施', perm: 'M10:fmea_document:read' } },
      { path: 'quality/fmea/:id/control-plan', name: 'FmeaControlPlan', component: () => import('@/pages/quality/fmea/ControlPlan.vue'), meta: { title: '控制计划', perm: 'M10:fmea_document:read' } },
      // 其他模块
      { path: 'energy', name: 'Energy', component: () => import('@/pages/energy/EnergyDeviceList.vue'), meta: { title: '能碳管理', perm: 'M11:energy_device:read' } },
      { path: 'energy/overview', name: 'EnergyOverview', component: () => import('@/pages/energy/EnergyOverview.vue'), meta: { title: '用能概况', perm: 'M11:energy_device:read' } },
      { path: 'energy/analysis', name: 'EnergyAnalysis', component: () => import('@/pages/energy/EnergyAnalysis.vue'), meta: { title: '能耗分析', perm: 'M11:energy_device:read' } },
      { path: 'energy/carbon', name: 'EnergyCarbon', component: () => import('@/pages/energy/EnergyCarbon.vue'), meta: { title: '碳管理', perm: 'M11:energy_device:read' } },
      { path: 'data-collection', name: 'DataCollection', component: () => import('@/pages/datacollection/CollectTaskList.vue'), meta: { title: '数据采集', perm: 'M12:collect_task:read' } },
      // perm 必须是"页面真正需要的接口权限"，不能拿一个更宽泛的码代替：
      // 用 PLAT:user:read 会让所有能看用户列表的人都能进这两页，
      // 而页面加载即调 /system/config、/system/license → 403（空白页）。
      { path: 'system/config', name: 'SystemConfig', component: () => import('@/pages/system/SystemConfig.vue'), meta: { title: '系统配置', perm: 'PLAT:system_config:read' } },
      { path: 'system/license', name: 'LicenseInfo', component: () => import('@/pages/system/LicenseInfo.vue'), meta: { title: '许可证', perm: 'PLAT:system_license:read' } },
      // 角色权限配置（S2 落地：权限码勾选 + 数据范围）
      { path: 'system/roles', name: 'RolePermissions', component: () => import('@/pages/system/RolePermissions.vue'), meta: { title: '角色权限', perm: 'PLAT:role_permission:read' } },
      // M20 - 仓储管理 (WMS)
      { path: 'wms/warehouse-tree', name: 'WarehouseTree', component: () => import('@/pages/wms/WarehouseTree.vue'), meta: { perm: 'M04:wms_warehouse:read', title: '仓库结构' } },
      { path: 'wms/materials', name: 'WmsMaterialList', component: () => import('@/pages/wms/MaterialList.vue'), meta: { perm: 'M04:wms_material:read', title: '物料主数据' } },
      { path: 'wms/receipt-orders', name: 'ReceiptOrderList', component: () => import('@/pages/wms/ReceiptOrderList.vue'), meta: { perm: 'M04:wms_receipt_order:read', title: '入库单管理' } },
      { path: 'wms/receipt-orders/create', name: 'CreateReceiptOrder', component: () => import('@/pages/wms/ReceiptOrderCreate.vue'), meta: { perm: 'M04:wms_receipt_order:read', title: '新增入库单' } },
      { path: 'wms/receipt-orders/:id', name: 'ReceiptOrderDetail', component: () => import('@/pages/wms/ReceiptOrderDetail.vue'), meta: { perm: 'M04:wms_receipt_order:read', title: '入库单详情' } },
      { path: 'wms/issue-orders', name: 'IssueOrderList', component: () => import('@/pages/wms/IssueOrderList.vue'), meta: { perm: 'M04:wms_issue_order:read', title: '出库单管理' } },
      { path: 'wms/stock-query', name: 'StockQuery', component: () => import('@/pages/wms/StockQuery.vue'), meta: { perm: 'M04:wms_inventory:read', title: '库存查询' } },
      { path: 'wms/inventory', redirect: '/wms/stock-query' },
      { path: 'wms/stock-move', name: 'StockMove', component: () => import('@/pages/wms/StockMove.vue'), meta: { perm: 'M04:wms_inventory:read', title: '库存移动' } },
      { path: 'wms/inventory-counts', name: 'CountList', component: () => import('@/pages/wms/CountList.vue'), meta: { perm: 'M04:wms_inventory_count:read', title: '盘点管理' } },
      { path: 'wms/batches', name: 'BatchList', component: () => import('@/pages/wms/BatchList.vue'), meta: { title: '批次管理' } },
      { path: 'wms/alerts', name: 'AlertList', component: () => import('@/pages/wms/AlertList.vue'), meta: { title: '库存预警' } },
      { path: 'wms/reports', name: 'StockReport', component: () => import('@/pages/wms/StockReport.vue'), meta: { title: '库存报表' } },
      // M16 - 试产管理
      { path: 'trials', name: 'TrialList', component: () => import('@/pages/trial/TrialList.vue'), meta: { title: '试产管理', perm: 'M16:trial:read' } },
      { path: 'trials/create', name: 'TrialCreate', component: () => import('@/pages/trial/TrialCreate.vue'), meta: { title: '新建试产', perm: 'M16:trial:read' } },
      { path: 'trials/:id', name: 'TrialDetail', component: () => import('@/pages/trial/TrialDetail.vue'), meta: { title: '试产详情', perm: 'M16:trial:read' } },
      // M15 - 实验室管理
      { path: 'lab', name: 'LabRequestList', component: () => import('@/pages/lab/RequestList.vue'), meta: { title: '实验室管理', perm: 'M15:lab_request:read' } },
      { path: 'lab/:id', name: 'LabRequestDetail', component: () => import('@/pages/lab/RequestDetail.vue'), meta: { title: '委托详情', perm: 'M15:lab_request:read' } },
      { path: 'lab/standards', name: 'LabStandardsList', component: () => import('@/pages/lab/StandardsList.vue'), meta: { title: '标准库', perm: 'M15:lab_standard:read' } },
    ],
  },
  // 404 兜底路由：未匹配路径显示 NotFound，避免白屏
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/pages/NotFound.vue') },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.path !== '/login' && !token) return '/login'

  // ── 权限守卫（S2）──
  // 优先用 permission 码（后端 RBAC 驱动）；老 token 无 permissions 时回退到 meta.roles。
  // 注意：前端守卫只负责"不把用户带进看不到的页面"，真正的拦截在后端 permission_guard。
  const requiredPerm = to.meta?.perm as string | undefined
  const requiredRoles = to.meta?.roles as string[] | undefined

  let perms: string[] = []
  let userRoles: string[] = []
  try {
    const raw = localStorage.getItem('user_info')
    if (raw) {
      const u = JSON.parse(raw)
      perms = Array.isArray(u.permissions) ? u.permissions : []
      userRoles = Array.isArray(u.roles) ? u.roles.map((r: any) => r?.code ?? r) : []
    }
  } catch { /* ignore */ }

  const adminBypass = userRoles.includes('admin') || perms.includes('*')

  if (requiredPerm) {
    const ok = adminBypass || matchPermission(perms, requiredPerm)
    if (!ok) {
      // 老数据兜底：permissions 为空但 roles 齐全 → 允许通过并告警（切换期不误伤）
      if (perms.length === 0 && userRoles.length > 0) {
        console.warn('[perm] 用户权限未加载，回退角色判断：', to.path)
        return true
      }
      return { path: '/403', query: { from: to.fullPath, perm: requiredPerm } }
    }
    return true
  }

  // 兼容：仍使用 meta.roles 的存量路由
  if (requiredRoles && requiredRoles.length > 0) {
    if (adminBypass) return true
    if (perms.length === 0 && userRoles.length === 0) return '/dashboard'
    if (perms.length > 0) return true   // 已接入权限体系的路由不再用角色判断
    if (!requiredRoles.some(r => userRoles.includes(r))) return '/dashboard'
  }
})

export default router
