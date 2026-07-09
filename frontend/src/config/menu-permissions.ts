export interface ChildPerm {
  childId: string
  roles: string[]
}

export interface MenuPermission {
  menuId: string
  roles?: string[]
  children?: ChildPerm[]
}

export const menuPermissions: MenuPermission[] = [
  { menuId: 'home' },
  {
    menuId: 'production',
    roles: ['admin', 'department_head', 'team_leader', 'scheduler', 'process_engineer', 'key_user'],
    children: [
      { childId: 'schedule', roles: ['admin', 'scheduler', 'department_head'] },
      { childId: 'boms', roles: ['admin', 'process_engineer', 'department_head'] },
    ],
  },
  {
    menuId: 'equipment',
    roles: ['admin', 'department_head', 'maintenance_tech', 'team_leader'],
  },
  {
    menuId: 'andon',
    children: [
      { childId: 'escalation_rules', roles: ['admin', 'department_head', 'key_user'] },
    ],
  },
  {
    menuId: 'quality',
    roles: ['admin', 'department_head', 'inspector', 'quality_engineer', 'key_user'],
    children: [
      { childId: 'spc_limits', roles: ['admin', 'quality_engineer'] },
      { childId: 'ppap_levels', roles: ['admin', 'quality_engineer'] },
      { childId: 'ppap_submissions', roles: ['admin', 'quality_engineer'] },
      { childId: 'ppap_elements', roles: ['admin', 'quality_engineer'] },
      { childId: 'fmea_list', roles: ['admin', 'quality_engineer', 'process_engineer'] },
    ],
  },
  {
    menuId: 'energy',
    roles: ['admin', 'department_head', 'key_user'],
  },
  {
    menuId: 'data_collection',
    roles: ['admin', 'department_head', 'key_user'],
  },
  {
    menuId: 'system',
    roles: ['admin', 'key_user'],
  },
  {
    menuId: 'trial',
    roles: ['admin', 'process_engineer', 'department_head'],
  },
  {
    menuId: 'lab',
    roles: ['admin', 'inspector', 'process_engineer', 'department_head'],
    children: [
      { childId: 'lab_standards', roles: ['admin', 'inspector', 'process_engineer'] },
    ],
  },
]
