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
  {
    menuId: 'energy',
    perm: 'M11:energy_device:read',
  },
  {
    menuId: 'data_collection',
    perm: 'M12:collect_task:read',
  },
  {
    menuId: 'system',
    perm: 'PLAT:user:read',
    children: [
      // 未列出的子菜单（系统配置 / 许可证）继承父级可见性
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
