# mfg1 E2E 全角色全流程测试 Buglist

测试时间: 2026-07-12T02:16:02.789Z
环境: mfg1.ziwi.cn (CVM 193.112.163.147)
测试用户: 10 (admin + 9 角色)
覆盖页面: 33 个

## 汇总
- 总问题数: 9

## 问题列表

### BUG-001: [network_error] 全模块//cockpit
- **角色**: admin
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-002: [network_error] 角色权限//cockpit
- **角色**: 部门主管
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-003: [network_error] 角色权限//cockpit
- **角色**: 班组长
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-004: [network_error] 角色权限//cockpit
- **角色**: 调度员
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-005: [network_error] 角色权限//cockpit
- **角色**: 工艺工程师
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-006: [network_error] 角色权限//cockpit
- **角色**: 关键用户
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-007: [network_error] 角色权限//cockpit
- **角色**: 维保员
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-008: [network_error] 角色权限//cockpit
- **角色**: 检验员
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

### BUG-009: [network_error] 角色权限//cockpit
- **角色**: 品质工程师
- **URL**: https://mfg1.ziwi.cn/api/v1/work-orders?page_size=1
- **消息**: net::ERR_ABORTED

