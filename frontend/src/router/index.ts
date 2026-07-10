import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

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
      { path: 'work-orders', name: 'WorkOrders', component: () => import('@/pages/production/WorkOrderList.vue'), meta: { roles: R_PROD } },
      { path: 'work-orders/create', name: 'CreateWorkOrder', component: () => import('@/pages/production/CreateWorkOrder.vue'), meta: { roles: R_PROD } },
      { path: 'work-orders/:id', name: 'WorkOrderDetail', component: () => import('@/pages/production/WorkOrderDetail.vue'), meta: { roles: R_PROD } },
      { path: 'work-reports', name: 'WorkReports', component: () => import('@/pages/production/WorkReportList.vue'), meta: { roles: R_PROD } },
      { path: 'work-reports/create', name: 'CreateReport', component: () => import('@/pages/production/WorkReportForm.vue'), meta: { roles: R_PROD } },
      { path: 'reports', name: 'Reports', component: () => import('@/pages/production/ReportView.vue'), meta: { roles: R_PROD } },
      { path: 'schedule', name: 'Schedule', component: () => import('@/pages/production/ScheduleGantt.vue'), meta: { title: '生产排产', roles: R_SCHEDULE } },
      // M02 - BOM管理
      { path: 'boms', name: 'BomList', component: () => import('@/pages/production/BomList.vue'), meta: { title: 'BOM管理', roles: R_BOMS } },
      // M04 - 工序定义
      { path: 'basics/operations', name: 'OperationList', component: () => import('@/pages/basics/OperationList.vue'), meta: { title: '工序定义' } },
      // M05 - 工作中心
      { path: 'basics/work-centers', name: 'WorkCenterList', component: () => import('@/pages/basics/WorkCenterList.vue'), meta: { title: '工作中心' } },
      // M03 - 工艺路线
      { path: 'basics/routes', name: 'RouteList', component: () => import('@/pages/basics/RouteList.vue'), meta: { title: '工艺路线' } },
      { path: 'basics/route-editor/:id', name: 'RouteEditor', component: () => import('@/pages/basics/RouteEditor.vue'), meta: { title: '工序编排' } },
      // M01 - 产品管理
      { path: 'basics/products', name: 'ProductList', component: () => import('@/pages/basics/ProductList.vue'), meta: { title: '产品管理' } },
      // M06 - 工厂日历
      { path: 'basics/calendar', name: 'CalendarView', component: () => import('@/pages/basics/CalendarView.vue'), meta: { title: '工厂日历' } },
      // TPM 设备管理
      { path: 'equipment', name: 'Equipment', component: () => import('@/pages/equipment/EquipmentList.vue'), meta: { title: '设备管理', roles: R_EQUIP } },
      { path: 'equipment/create', name: 'CreateEquipment', component: () => import('@/pages/equipment/EquipmentCreate.vue'), meta: { title: '新增设备', roles: R_EQUIP } },
      { path: 'equipment/:id', name: 'EquipmentDetail', component: () => import('@/pages/equipment/EquipmentDetail.vue'), meta: { title: '设备详情', roles: R_EQUIP } },
      { path: 'equipment/maintenance-tasks', name: 'MaintenanceTasks', component: () => import('@/pages/equipment/MaintenanceTasks.vue'), meta: { title: '保养任务', roles: R_EQUIP } },
      { path: 'equipment/maintenance-plans', name: 'MaintenancePlans', component: () => import('@/pages/equipment/MaintenancePlans.vue'), meta: { title: '维护计划', roles: R_EQUIP } },
      // M05 - 安灯管理
      { path: 'andon', name: 'Andon', component: () => import('@/pages/andon/AndonList.vue'), meta: { title: '安灯管理' } },
      { path: 'andon/:id', name: 'AndonDetail', component: () => import('@/pages/andon/AndonDetail.vue'), meta: { title: '安灯详情' } },
      // M11 - 升级规则配置
      { path: 'andon/escalation-rules', name: 'EscalationRules', component: () => import('@/pages/andon/EscalationRules.vue'), meta: { title: '升级规则配置', roles: ['admin', 'department_head', 'key_user'] } },
      // M03 - 品质管理
      { path: 'quality', name: 'Quality', component: () => import('@/pages/quality/InspectionList.vue'), meta: { title: '品质管理', roles: R_QUALITY } },
      { path: 'quality/create', name: 'CreateInspection', component: () => import('@/pages/quality/InspectionCreate.vue'), meta: { title: '新建检验', roles: R_QUALITY } },
      { path: 'quality/:id', name: 'QualityDetail', component: () => import('@/pages/quality/InspectionDetail.vue'), meta: { title: '检验详情', roles: R_QUALITY } },
      // SPC 统计分析
      { path: 'quality/spc/control-limits', name: 'SpcControlLimits', component: () => import('@/pages/quality/spc/ControlLimitList.vue'), meta: { title: 'SPC控制限配置', roles: R_SPC } },
      { path: 'quality/spc/control-limits/:id/chart', name: 'SpcControlChart', component: () => import('@/pages/quality/spc/ControlChart.vue'), meta: { title: 'SPC控制图', roles: R_SPC } },
      { path: 'quality/spc/control-limits/:id/capability', name: 'SpcCapability', component: () => import('@/pages/quality/spc/CapabilityAnalysis.vue'), meta: { title: '过程能力分析', roles: R_SPC } },
      // PPAP
      { path: 'quality/ppap/levels', name: 'PpapLevels', component: () => import('@/pages/quality/ppap/PpapLevels.vue'), meta: { title: 'PPAP等级配置', roles: R_PPAP } },
      { path: 'quality/ppap/submissions', name: 'PpapSubmissions', component: () => import('@/pages/quality/ppap/PpapSubmissions.vue'), meta: { title: 'PPAP提交管理', roles: R_PPAP } },
      { path: 'quality/ppap/elements', name: 'PpapElements', component: () => import('@/pages/quality/ppap/PpapElements.vue'), meta: { title: 'PPAP要素模板', roles: R_PPAP } },
      // FMEA
      { path: 'quality/fmea', name: 'FmeaList', component: () => import('@/pages/quality/fmea/FmeaList.vue'), meta: { title: 'FMEA管理', roles: R_FMEA } },
      { path: 'quality/fmea/:id/edit', name: 'FmeaEditor', component: () => import('@/pages/quality/fmea/FmeaEditor.vue'), meta: { title: 'FMEA编辑', roles: R_FMEA } },
      { path: 'quality/fmea/:id/actions', name: 'FmeaActions', component: () => import('@/pages/quality/fmea/FmeaActions.vue'), meta: { title: 'FMEA整改措施', roles: R_FMEA } },
      { path: 'quality/fmea/:id/control-plan', name: 'FmeaControlPlan', component: () => import('@/pages/quality/fmea/ControlPlan.vue'), meta: { title: '控制计划', roles: R_FMEA } },
      // 其他模块
      { path: 'energy', name: 'Energy', component: () => import('@/pages/energy/EnergyDeviceList.vue'), meta: { title: '能碳管理', roles: R_ENERGY } },
      { path: 'energy/overview', name: 'EnergyOverview', component: () => import('@/pages/energy/EnergyOverview.vue'), meta: { title: '用能概况', roles: R_ENERGY } },
      { path: 'energy/analysis', name: 'EnergyAnalysis', component: () => import('@/pages/energy/EnergyAnalysis.vue'), meta: { title: '能耗分析', roles: R_ENERGY } },
      { path: 'energy/carbon', name: 'EnergyCarbon', component: () => import('@/pages/energy/EnergyCarbon.vue'), meta: { title: '碳管理', roles: R_ENERGY } },
      { path: 'data-collection', name: 'DataCollection', component: () => import('@/pages/datacollection/CollectTaskList.vue'), meta: { title: '数据采集', roles: R_DC } },
      { path: 'system/config', name: 'SystemConfig', component: () => import('@/pages/system/SystemConfig.vue'), meta: { title: '系统配置', roles: R_SYSTEM } },
      { path: 'system/license', name: 'LicenseInfo', component: () => import('@/pages/system/LicenseInfo.vue'), meta: { title: '许可证', roles: R_SYSTEM } },
      // M20 - 仓储管理 (WMS)
      { path: 'wms/warehouse-tree', name: 'WarehouseTree', component: () => import('@/pages/wms/WarehouseTree.vue'), meta: { title: '仓库结构' } },
      { path: 'wms/materials', name: 'WmsMaterialList', component: () => import('@/pages/wms/MaterialList.vue'), meta: { title: '物料主数据' } },
      { path: 'wms/receipt-orders', name: 'ReceiptOrderList', component: () => import('@/pages/wms/ReceiptOrderList.vue'), meta: { title: '入库单管理' } },
      { path: 'wms/issue-orders', name: 'IssueOrderList', component: () => import('@/pages/wms/IssueOrderList.vue'), meta: { title: '出库单管理' } },
      { path: 'wms/stock-query', name: 'StockQuery', component: () => import('@/pages/wms/StockQuery.vue'), meta: { title: '库存查询' } },
      { path: 'wms/stock-move', name: 'StockMove', component: () => import('@/pages/wms/StockMove.vue'), meta: { title: '库存移动' } },
      { path: 'wms/inventory-counts', name: 'CountList', component: () => import('@/pages/wms/CountList.vue'), meta: { title: '盘点管理' } },
      { path: 'wms/batches', name: 'BatchList', component: () => import('@/pages/wms/BatchList.vue'), meta: { title: '批次管理' } },
      { path: 'wms/alerts', name: 'AlertList', component: () => import('@/pages/wms/AlertList.vue'), meta: { title: '库存预警' } },
      { path: 'wms/reports', name: 'StockReport', component: () => import('@/pages/wms/StockReport.vue'), meta: { title: '库存报表' } },
      // M16 - 试产管理
      { path: 'trials', name: 'TrialList', component: () => import('@/pages/trial/TrialList.vue'), meta: { title: '试产管理', roles: R_TRIAL } },
      { path: 'trials/create', name: 'TrialCreate', component: () => import('@/pages/trial/TrialCreate.vue'), meta: { title: '新建试产', roles: R_TRIAL } },
      { path: 'trials/:id', name: 'TrialDetail', component: () => import('@/pages/trial/TrialDetail.vue'), meta: { title: '试产详情', roles: R_TRIAL } },
      // M15 - 实验室管理
      { path: 'lab', name: 'LabRequestList', component: () => import('@/pages/lab/RequestList.vue'), meta: { title: '实验室管理', roles: ['admin', 'inspector', 'process_engineer', 'department_head'] } },
      { path: 'lab/:id', name: 'LabRequestDetail', component: () => import('@/pages/lab/RequestDetail.vue'), meta: { title: '委托详情', roles: ['admin', 'inspector', 'process_engineer', 'department_head'] } },
      { path: 'lab/standards', name: 'LabStandardsList', component: () => import('@/pages/lab/StandardsList.vue'), meta: { title: '标准库', roles: ['admin', 'inspector', 'process_engineer'] } },
    ],
  },
  // 404 兜底路由：未匹配路径显示 NotFound，避免白屏
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/pages/NotFound.vue') },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.path !== '/login' && !token) return '/login'

  // 路由角色守卫
  const requiredRoles = to.meta?.roles as string[] | undefined
  if (requiredRoles && requiredRoles.length > 0) {
    try {
      const raw = localStorage.getItem('user_info')
      if (raw) {
        const u = JSON.parse(raw)
        const userRoles: string[] = u.roles
          ? (Array.isArray(u.roles) ? u.roles.map((r: any) => r.code ?? r) : [])
          : []
        // admin 绕过所有限制
        if (userRoles.includes('admin')) return true
        // 检查是否有所需角色
        const hasRole = requiredRoles.some(r => userRoles.includes(r))
        if (!hasRole) return '/dashboard'
      } else {
        return '/dashboard'
      }
    } catch {
      return '/dashboard'
    }
  }
})

export default router
