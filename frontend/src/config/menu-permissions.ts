/**
 * 菜单权限配置（S2：由角色驱动改为权限码驱动）
 *
 * 改造前：`roles: ['admin', 'inspector', ...]` —— 硬编码角色名，租户自建角色接不进来。
 * 改造后：`perm: 'M03:inspection_order:read'` —— 与后端 `permissions` 表同一套码。
 *
 * 判定规则与后端 `has_permission` 一致（见 stores/auth.ts 的 matchPermission），
 * 支持 `*` / `M01:*` / `M01:work_order:*` / `*:read` 四级通配。
 *
 * 未在此文件中出现的菜单 = 不做权限限制（登录即可见）。
 * 新增菜单时请优先补 perm，而不是留空。
 */

export interface ChildPerm {
  childId: string
  /** 需要的权限码 */
  perm?: string
}

export interface MenuPermission {
  menuId: string
  /** 菜单本身需要的权限码 */
  perm?: string
  children?: ChildPerm[]
}

export const menuPermissions: MenuPermission[] = [
  { menuId: 'home' },

  // 基础数据：当前所有登录用户可见（M00 只读）
  {
    menuId: 'basics',
    perm: 'M00:product:read',
    children: [
      { childId: 'op_operations', perm: 'M00:operation:read' },
      { childId: 'op_workcenters', perm: 'M00:work_center:read' },
      { childId: 'op_routes', perm: 'M00:route:read' },
      { childId: 'op_products', perm: 'M00:product:read' },
      { childId: 'op_calendar', perm: 'M00:calendar:read' },
    ],
  },
  {
    menuId: 'production',
    perm: 'M01:work_order:read',
    children: [
      { childId: 'work_orders', perm: 'M01:work_order:read' },
      { childId: 'work_reports', perm: 'M01:work_report:read' },
      { childId: 'reports', perm: 'M01:report_daily:read' },
      { childId: 'schedule', perm: 'M01:work_order:read' },
      { childId: 'boms', perm: 'M02:bom:read' },
    ],
  },
  {
    menuId: 'equipment',
    perm: 'M06:equipment:read',
    // T02：设备模块三个子菜单显式登记（与 MainLayout 的 children id 一一对应）。
    // 术语按 Q5 统一为「保养任务 / 保养计划」，与旧称彻底切开。
    // 三者当前共用 M06:equipment:read（后端未拆分更细的码）；显式写出是为了
    // 将来拆码时只改这里，不用回头翻 MainLayout。
    children: [
      { childId: 'equipment_list', perm: 'M06:equipment:read' },
      { childId: 'maintenance_tasks', perm: 'M06:equipment:read' },
      { childId: 'maintenance_plans', perm: 'M06:equipment:read' },
    ],
  },
  {
    menuId: 'andon',
    perm: 'M05:andon_call:read',
    children: [
      { childId: 'escalation_rules', perm: 'M05:andon_escalation_rule:read' },
    ],
  },
  {
    menuId: 'quality',
    perm: 'M03:inspection_order:read',
    children: [
      { childId: 'spc_limits', perm: 'M10:spc_control_limit:read' },
      { childId: 'ppap_levels', perm: 'M10:ppap_level:read' },
      { childId: 'ppap_submissions', perm: 'M10:ppap_submission:read' },
      { childId: 'ppap_elements', perm: 'M10:ppap_element:read' },
      { childId: 'fmea_list', perm: 'M10:fmea_document:read' },
    ],
  },
  // 能碳（energy）刻意不在这里登记权限：
  // 它是跳到 ECMS 的外链，能不能用由 ECMS 按 license 判定。
  // 若还挂 M11:energy_device:read，没开 M11 权限的角色就看不到入口 ——
  // 而他在 ECMS 里可能本来就有权，等于被 mfg 的权限表误伤。
  {
    menuId: 'data_collection',
    perm: 'M12:collect_task:read',
  },
  {
    menuId: 'system',
    perm: 'PLAT:user:read',
    children: [
      // 必须逐项声明：子菜单不声明时会继承父级的 PLAT:user:read，
      // 于是"能看用户列表"的人也能看见系统配置/许可证 ——
      // 点进去后端要 PLAT:system_config / system_license，直接 403。
      // （强制模式全角色回归实测：9 个非 admin 账号里 8 个撞在这两页上。）
      { childId: 'system_config', perm: 'PLAT:system_config:read' },
      { childId: 'system_license', perm: 'PLAT:system_license:read' },
      { childId: 'system_roles', perm: 'PLAT:role_permission:read' },
    ],
  },
  {
    menuId: 'trial',
    perm: 'M16:trial:read',
  },
  {
    menuId: 'lab',
    perm: 'M15:lab_request:read',
    children: [
      { childId: 'lab_standards', perm: 'M15:lab_standard:read' },
    ],
  },
]
