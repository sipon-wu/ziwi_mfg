# mfg1 预发布环境 — 虚拟工厂仿真数据规划 v2.0

> 更新说明：根据 Kane 反馈，补充供应商、客户、BOM 齐套、仓别、物料流转等全部数据维度。
> 实际数据库摸查：当前无 suppliers/customers/sales_orders 独立表，seed 脚本将使用虚拟 ID 引用并在文档中注明。

---

## 1. 虚拟工厂简介

### 工厂概况
| 项目 | 内容 |
|:---|:---|
| 工厂名称 | **星辰精密制造厂**（Xingchen Precision Mfg） |
| 行业类型 | 离散制造 — 精密金属/机械零部件 |
| 车间 | 2 个：机加工一车间（M01）、机加工二车间（M02） |
| 产品 | 3 种：轴承座、法兰盘、传动轴 |
| 设备 | 12 台（加工中心×2、数控车床×3、铣床×2、磨床×2、三坐标、硬度计、粗糙度仪） |
| 仓库 | 4 个：原料仓、半成品仓、成品仓、备品备件仓 |
| 供应商 | 3 家（虚拟） |
| 客户 | 2 家（虚拟，用于 PPAP 提交） |
| 员工 | 10 人（对应 10 个测试用户） |
| 工作日历 | 2026 年 7-12 月（周一至周五双班，周六单班） |

### 数据流转全景（含物料流）
```
供应商交付 ──→ 采购入库 (receipt_order + receipt_order_items)
                   ↓
              原料仓 (warehouse: WH-RAW)
                   ↓
              领料申请 (material_request + material_request_items)
                   ↓
              原料出库 (issue_order + issue_order_items)
                   ↓
              ┌──────────────────────────────────────────────┐
              │          生产工单 (work_order)                 │
              │  ├── 工序① 来料检 (inspection)               │
              │  ├── 工序② 粗车 (work_report + 能耗)        │
              │  ├── 工序③ 精车 (work_report + SPC抽检)     │
              │  ├── 工序④ 钻孔 (work_report + 安灯异常)    │
              │  ├── 工序⑤ 过程检 (inspection)              │
              │  └── 工序⑥ 成品检 (inspection)              │
              └──────────────────────────────────────────────┘
                   ↓
          (良品) → 半成品/成品入库 (inventory + inventory_transactions)
          (次品) → 废品统计 (scrap_qty in work_report)
                   ↓
              成品仓 (warehouse: WH-FG)
```

### 数据依赖关系
```
suppliers(虚拟) → receipt_orders → receipt_order_items → inventory_transactions
customers(虚拟) → ppap_submissions

materials → product_bom → products
operations → route_steps → process_routes → product_routes → products

products/materials → work_orders → work_reports → inspection_order → inspection_result
                                    → andon_call → andon_response
                                    → bom_snapshots

equipment_categories → equipment → maintenance_plans → maintenance_tasks
equipment → wc_equipments → work_centers → route_steps

energy_device → carbon_emission_record
             → energy_alert

materials → inventory → inventory_transactions
warehouses → warehouse_zones → warehouse_locations → inventory
material_requests → issue_orders → issue_order_items → inventory_transactions
```

---

## 2. 供应商与客户数据

### ⚠️ 说明
当前数据库 schema **没有独立的 `suppliers`/`customers` 表**。`receipt_orders.supplier_id` 和 `ppap_submissions.customer_id` 为 bigint 外键。Seed 脚本中将使用虚拟 ID（1,2,3）引用，并在数据注释中标注供应商/客户名称。如需独立表管理，属于后续功能开发范围。

### 虚拟供应商（3 家）
| ID | 名称 | 供应品类 | 说明 |
|:---|:---|:---|:---|
| 1 | 重庆钢铁集团 | 45#圆钢、轴承钢 | 主要原材料供应商 |
| 2 | 成都铸件厂 | HT200 铸铁毛坯 | 铸件毛坯供应商 |
| 3 | 标准件批发公司 | 螺栓、垫片、密封圈 | 标准件/五金件供应商 |

### 虚拟客户（2 家，用于 PPAP）
| ID | 名称 | PPAP 产品 |
|:---|:---|:---|
| 1 | 重庆通用机械厂 | 轴承座/法兰盘 |
| 2 | 成都精密装备公司 | 传动轴总成 |

---

## 3. 基础数据模块（Phase 1）

### 3.1 工序定义 (operations) — 10 条
| code | name | op_type | setup_time(min) | unit_time(min) |
|:---|:---|:---|:---:|:---:|
| OP-0010 | 原材料检验 | incoming_qc | 0 | 5 |
| OP-0020 | 粗车外圆 | machining | 15 | 20 |
| OP-0030 | 精车外圆 | machining | 10 | 25 |
| OP-0040 | 铣削端面 | machining | 12 | 15 |
| OP-0050 | 钻孔攻丝 | machining | 10 | 12 |
| OP-0060 | 热处理 | heat_treat | 30 | 60 |
| OP-0070 | 外圆磨削 | machining | 15 | 18 |
| OP-0080 | 过程检验 | process_qc | 0 | 8 |
| OP-0090 | 总装配 | assembly | 10 | 15 |
| OP-0100 | 成品检验 | final_qc | 0 | 10 |

### 3.2 工作中心 (work_centers) — 6 个
| code | name | wc_type | efficiency | capacity_per_shift |
|:---|:---|:---|:---:|:---:|
| WC-CNC | CNC 加工中心 | machining | 0.92 | 80 |
| WC-LATHE | 车床工段 | machining | 0.90 | 60 |
| WC-MILL | 铣床工段 | machining | 0.88 | 50 |
| WC-GRIND | 磨床工段 | machining | 0.85 | 40 |
| WC-ASM | 装配线 | assembly | 0.95 | 30 |
| WC-QC | 检验站 | quality | 1.0 | 20 |

### 3.3 设备分类 (equipment_categories) — 5 个
| code | name | level | sort_order |
|:---|:---|:---:|:---:|
| CAT-CNC | CNC 加工中心 | 1 | 1 |
| CAT-LATHE | 数控车床 | 1 | 2 |
| CAT-MILL | 普通铣床 | 1 | 3 |
| CAT-GRIND | 磨床 | 1 | 4 |
| CAT-QC | 检测设备 | 1 | 5 |

### 3.4 设备 (equipment) — 12 台
| code | name | category | model | location | status | power_kw |
|:---|:---|:---|:---|:---|:---:|:---:|
| MC-001 | 立式加工中心 VMC850 | CAT-CNC | VMC850 | M01-A区 | running | 18.5 |
| MC-002 | 卧式加工中心 HMC630 | CAT-CNC | HMC630 | M01-A区 | running | 22.0 |
| LT-001 | 数控车床 CK6140 | CAT-LATHE | CK6140 | M01-B区 | running | 7.5 |
| LT-002 | 数控车床 CK6150 | CAT-LATHE | CK6150 | M01-B区 | running | 11.0 |
| LT-003 | 数控车床 CK6136 | CAT-LATHE | CK6136 | M01-B区 | idle | 5.5 |
| ML-001 | 立式铣床 X5032 | CAT-MILL | X5032 | M02-A区 | running | 7.5 |
| ML-002 | 数控铣床 XK714 | CAT-MILL | XK714 | M02-A区 | running | 15.0 |
| GR-001 | 外圆磨床 M1432 | CAT-GRIND | M1432 | M02-B区 | running | 9.0 |
| GR-002 | 平面磨床 M7130 | CAT-GRIND | M7130 | M02-B区 | maintenance | 7.5 |
| CMM-001 | 三坐标测量机 | CAT-QC | CONTURA | 质检中心 | running | 1.5 |
| HT-001 | 硬度计 HR-150A | CAT-QC | HR-150A | 质检中心 | running | 0.3 |
| RT-001 | 粗糙度仪 TR200 | CAT-QC | TR200 | 质检中心 | running | 0.1 |

### 3.5 员工/班组 (employees + teams)
| username | real_name | position | team | 角色 |
|:---|:---|:---|:---|:---|
| test_dept_head | 测试部门主管 | 生产部长 | 管理组 | department_head |
| test_team_leader | 测试班组长 | 班组长 | 机加班 | team_leader |
| test_scheduler | 测试调度员 | 调度员 | 管理组 | scheduler |
| test_proc_eng | 测试工艺工程师 | 工艺工程师 | 技术组 | process_engineer |
| test_key_user | 测试关键用户 | 生产主管 | 管理组 | key_user |
| test_maint_tech | 测试设备维保员 | 设备维保 | 维修组 | maintenance_tech |
| test_inspector | 测试品质检验员 | 质检员 | 质检组 | inspector |
| test_quality_eng | 测试品质工程师 | 品质工程师 | 质检组 | quality_engineer |
| test_admin | test 系统管理员 | 系统管理员 | 管理组 | admin |
| mfg_admin | mfg 平台管理员 | 厂长 | 管理组 | admin |

### 3.6 设备-工作中心关联 (wc_equipments)
| wc | 设备 | is_primary |
|:---|:---|:---:|
| WC-CNC | MC-001, MC-002 | Y |
| WC-LATHE | LT-001, LT-002, LT-003 | LT-001(Y) |
| WC-MILL | ML-001, ML-002 | Y |
| WC-GRIND | GR-001, GR-002 | Y |
| WC-QC | CMM-001, HT-001, RT-001 | CMM-001(Y) |

---

## 4. 产品/BOM/工艺路线（核心 — 齐套数据）

### 4.1 物料定义 (materials) — 9 种
| code | name | spec | unit | material_type | material_category | min_stock | max_stock |
|:---|:---|:---|:---:|:---|:---|:---:|:---:|
| M-001 | 45#圆钢 | φ80×150mm | 根 | raw | 金属材料 | 50 | 500 |
| M-002 | HT200 铸铁毛坯 | 轴承座毛坯 | 件 | raw | 铸件 | 30 | 300 |
| M-003 | 法兰毛坯 | φ200×30mm | 件 | raw | 铸件 | 40 | 400 |
| M-004 | 传动轴锻件 | φ50×300mm | 根 | raw | 金属材料 | 20 | 200 |
| M-005 | 齿轮 20CrMnTi | m3×z20 | 件 | semi | 外购件 | 50 | 300 |
| M-006 | 轴承 6205 | 6205-2RS | 套 | semi | 标准件 | 100 | 1000 |
| M-007 | 螺栓 M8×20 | M8×20 8.8级 | 颗 | semi | 标准件 | 200 | 2000 |
| M-008 | 平垫圈 M8 | M8 镀锌 | 颗 | semi | 标准件 | 200 | 2000 |
| M-009 | 润滑油 L-HM46 | 18L/桶 | 桶 | raw | 辅料 | 2 | 20 |

### 4.2 产品定义 (products) — 3 个
| code | name | spec | unit | product_type | weight(kg) |
|:---|:---|:---|:---:|:---|:---:|
| PRO-001 | 精密轴承座 | ZCZ-200 | 件 | finished | 3.5 |
| PRO-002 | 法兰盘 | FLG-150 | 件 | finished | 1.8 |
| PRO-003 | 传动轴总成 | CS-300 | 件 | finished | 5.2 |

### 4.3 BOM 结构 (product_bom) — 完整齐套

**PRO-001 精密轴承座 (ZCZ-200)：**
| material_code | material_name | qty_per_unit | unit | material_type | scrap_rate | is_key | issue_op |
|:---|:---|:---:|:---|:---|:---:|:---:|:---|
| M-002 | HT200 铸铁毛坯 | 1 | 件 | raw | 3% | Y | OP-0010 |
| M-007 | 螺栓 M8×20 | 4 | 颗 | semi | 1% | N | OP-0050 |
| M-008 | 平垫圈 M8 | 4 | 颗 | semi | 1% | N | OP-0090 |
| M-009 | 润滑油 L-HM46 | 0.02 | 桶 | raw | 0% | N | OP-0020 |

**PRO-002 法兰盘 (FLG-150)：**
| material_code | material_name | qty_per_unit | unit | material_type | scrap_rate | is_key | issue_op |
|:---|:---|:---:|:---|:---|:---:|:---:|:---|
| M-003 | 法兰毛坯 | 1 | 件 | raw | 4% | Y | OP-0010 |
| M-009 | 润滑油 L-HM46 | 0.015 | 桶 | raw | 0% | N | OP-0020 |

**PRO-003 传动轴总成 (CS-300)：**
| material_code | material_name | qty_per_unit | unit | material_type | scrap_rate | is_key | issue_op |
|:---|:---|:---:|:---|:---|:---:|:---:|:---|
| M-001 | 45#圆钢 | 1 | 根 | raw | 5% | Y | OP-0010 |
| M-005 | 齿轮 20CrMnTi | 1 | 件 | semi | 2% | Y | OP-0090 |
| M-006 | 轴承 6205 | 2 | 套 | semi | 1% | Y | OP-0090 |
| M-007 | 螺栓 M8×20 | 6 | 颗 | semi | 1% | N | OP-0090 |
| M-008 | 平垫圈 M8 | 6 | 颗 | semi | 1% | N | OP-0090 |
| M-009 | 润滑油 L-HM46 | 0.03 | 桶 | raw | 0% | N | OP-0020 |

### 4.4 工艺路线 (process_routes) + 步骤 (route_steps) — 3 条

**RTE-BEARING — 轴承座工艺路线：**
| seq | operation | wc | setup_min | run_min | qc | description |
|:---:|:---|:---|:---:|:---:|:---|:---|
| 10 | OP-0010 原材料检验 | WC-QC | 0 | 5 | Y | 来料尺寸/硬度检验 |
| 20 | OP-0020 粗车外圆 | WC-LATHE | 15 | 20 | N | 粗加工外圆面留余量1mm |
| 30 | OP-0030 精车外圆 | WC-LATHE | 10 | 25 | Y(SPC) | 精加工到图纸公差φ200±0.05 |
| 40 | OP-0040 铣削端面 | WC-MILL | 12 | 15 | N | 铣端面/开槽 |
| 50 | OP-0050 钻孔攻丝 | WC-CNC | 10 | 12 | Y(SPC) | 钻4×M8孔+攻丝 |
| 60 | OP-0080 过程检验 | WC-QC | 0 | 8 | Y | 全部尺寸中间检查 |
| 70 | OP-0100 成品检验 | WC-QC | 0 | 10 | Y | 出库前全检 |

**RTE-FLANGE — 法兰盘工艺路线：**
| seq | operation | wc | setup_min | run_min | qc | description |
|:---:|:---|:---|:---:|:---:|:---|:---|
| 10 | OP-0010 原材料检验 | WC-QC | 0 | 5 | Y | 毛坯检验 |
| 20 | OP-0020 粗车外圆 | WC-LATHE | 12 | 18 | N | 粗加工 |
| 30 | OP-0030 精车外圆 | WC-LATHE | 10 | 22 | Y(SPC) | 精加工到尺寸 |
| 40 | OP-0040 铣削端面 | WC-MILL | 10 | 12 | N | 铣端面 |
| 50 | OP-0050 钻孔攻丝 | WC-MILL | 8 | 10 | N | 钻孔 |
| 60 | OP-0080 过程检验 | WC-QC | 0 | 6 | Y | 中间检查 |
| 70 | OP-0100 成品检验 | WC-QC | 0 | 8 | Y | 全检 |

**RTE-SHAFT — 传动轴工艺路线：**
| seq | operation | wc | setup_min | run_min | qc | description |
|:---:|:---|:---|:---:|:---:|:---|:---|
| 10 | OP-0010 原材料检验 | WC-QC | 0 | 5 | Y | 来料检验 |
| 20 | OP-0020 粗车外圆 | WC-LATHE | 15 | 25 | N | 粗加工 |
| 30 | OP-0060 热处理 | WC-GRIND | 30 | 60 | Y | 调质处理HRC48-52 |
| 40 | OP-0070 外圆磨削 | WC-GRIND | 15 | 18 | Y(SPC) | 磨削到最终尺寸 |
| 50 | OP-0050 钻孔攻丝 | WC-CNC | 10 | 15 | N | 钻孔/攻丝 |
| 60 | OP-0080 过程检验 | WC-QC | 0 | 10 | Y | 中间检查 |
| 70 | OP-0090 总装配 | WC-ASM | 10 | 15 | Y | 装齿轮/轴承 |
| 80 | OP-0100 成品检验 | WC-QC | 0 | 12 | Y | 全检 |

### 4.5 产品-路线关联 (product_routes)
| product | route | is_default |
|:---|:---|:---:|
| PRO-001 | RTE-BEARING | Y |
| PRO-002 | RTE-FLANGE | Y |
| PRO-003 | RTE-SHAFT | Y |

---

## 5. 仓库与库存模块（Phase 4）

### 5.1 仓库 (warehouses) — 4 个
| code | name | type | 说明 |
|:---|:---|:---|:---|
| WH-RAW | 原料库 | raw_material | 钢铁/铸件原料存放 |
| WH-WIP | 半成品库 | wip | 加工到一半的半成品 |
| WH-FG | 成品库 | finished | 产成品/可发货库存 |
| WH-SPARE | 备品备件库 | spare_parts | 备件/辅料/工具 |

### 5.2 仓库区域 (warehouse_zones) — 8 个
| warehouse | zone_code | zone_name | zone_type |
|:---|:---|:---|:---|
| WH-RAW | RAW-A | 钢材区 | rack |
| WH-RAW | RAW-B | 铸件区 | shelf |
| WH-WIP | WIP-A | 机加工半成品区 | rack |
| WH-WIP | WIP-B | 热处理半成品区 | shelf |
| WH-FG | FG-A | 轴承座成品区 | rack |
| WH-FG | FG-B | 法兰/传动轴成品区 | rack |
| WH-SPARE | SPA-A | 标准件区 | shelf |
| WH-SPARE | SPA-B | 润滑油/辅料区 | shelf |

### 5.3 库位 (warehouse_locations) — 20 个
每个区域 2-3 个库位编码（如 RAW-A-01, RAW-A-02），配置容量上限。

### 5.4 初始库存 (inventory) — 各物料可发库存
| material | warehouse | qty | unit | 说明 |
|:---|:---|:---:|:---|:---|
| M-001 45#圆钢 | WH-RAW | 300 | 根 | 安全库存 50 |
| M-002 铸铁毛坯 | WH-RAW | 150 | 件 | 安全库存 30 |
| M-003 法兰毛坯 | WH-RAW | 200 | 件 | 安全库存 40 |
| M-004 传动轴锻件 | WH-RAW | 100 | 根 | 安全库存 20 |
| M-005 齿轮 | WH-SPARE | 200 | 套 | 安全库存 50 |
| M-006 轴承6205 | WH-SPARE | 500 | 套 | 安全库存 100 |
| M-007 螺栓M8 | WH-SPARE | 1000 | 颗 | 安全库存 200 |
| M-008 垫圈M8 | WH-SPARE | 1000 | 颗 | 安全库存 200 |
| M-009 润滑油 | WH-SPARE | 10 | 桶 | 安全库存 2 |

### 5.5 批次 (batches) — 主要物料各 2-3 个批次
| material | batch_no | qty | supplier_batch |
|:---|:---|:---:|:---|
| M-001 45#圆钢 | B20260701 | 200 | CG-2026-0601 |
| M-001 45#圆钢 | B20260705 | 100 | CG-2026-0615 |
| M-002 铸铁毛坯 | B20260702 | 120 | CD-2026-0605 |
| ... | ... | ... | ... |

---

## 6. 物料流转数据（核心新增）

### 6.1 采购入库 (receipt_orders) — 6 条
覆盖本月近 2 周的来料记录，体现供应商→仓库的物料流入：
| receipt_no | supplier_id | type | status | warehouse | 物料/数量 | 日期 |
|:---|:---:|:---|:---|:---|:---|:---:|
| RCV-2026-0701 | 1(重钢) | purchase | completed | WH-RAW | 45#圆钢×200根 | 7/1 |
| RCV-2026-0702 | 2(成都铸件) | purchase | completed | WH-RAW | 铸铁毛坯×150件 | 7/2 |
| RCV-2026-0703 | 3(标准件) | purchase | completed | WH-SPARE | 螺栓/垫圈各500 | 7/3 |
| RCV-2026-0704 | 2(成都铸件) | purchase | completed | WH-RAW | 法兰毛坯×200件 | 7/6 |
| RCV-2026-0705 | 1(重钢) | purchase | partial | WH-RAW | 传动轴锻件×50件 | 7/8 |
| RCV-2026-0706 | 3(标准件) | return | completed | WH-SPARE | 不良品退货 | 7/9 |

### 6.2 领料申请 (material_requests) — 8 条
工单投产前发起领料申请，关联对应工单：
| request_no | work_order | warehouse | status | 物料/数量 |
|:---|:---|:---|:---|:---|
| MR-0701 | WO-2026-0701 | WH-RAW | completed | 铸铁毛坯×50 |
| MR-0702 | WO-2026-0704 | WH-RAW | completed | 铸铁毛坯×80 |
| MR-0703 | WO-2026-0702 | WH-RAW | completed | 法兰毛坯×100 |
| MR-0704 | WO-2026-0713 | WH-RAW | approved | 铸铁毛坯×45 |
| MR-0705 | WO-2026-0706 | WH-RAW | completed | 铸铁毛坯×40 |
| MR-0706 | WO-2026-0715 | WH-RAW | pending | 45#圆钢×15 |
| MR-0707 | WO-2026-0712 | WH-SPARE | completed | 轴承/螺栓/垫圈 |
| MR-0708 | WO-2026-0703 | WH-RAW | completed | 45#圆钢×30+辅料 |

### 6.3 生产出库 (issue_orders) — 6 条
仓管根据已批准的领料单执行出库：
| issue_no | mr_no | warehouse | status | 总数量 |
|:---|:---|:---|:---:|:---|
| ISS-0701 | MR-0701 | WH-RAW | completed | 50件 |
| ISS-0702 | MR-0702 | WH-RAW | completed | 80件 |
| ISS-0703 | MR-0703 | WH-RAW | completed | 100件 |
| ISS-0704 | MR-0704 | WH-RAW | completed | 45件 |
| ISS-0705 | MR-0705 | WH-RAW | completed | 40件 |
| ISS-0706 | MR-0706 | WH-RAW | partial | 10/15根 |

### 6.4 库存流水 (inventory_transactions) — 20+ 条
每条出入库均产生 transaction 记录：
- receipt 类型: `in` — 采购入库、退货入库
- issue 类型: `out` — 生产领料出库
- transfer 类型: `transfer` — 仓库间调拨（如原料→半成品）
- adjustment 类型: `adjustment` — 盘点调整

### 6.5 库存预警 (inventory_alerts) — 2 条
- M-001 45#圆钢库存低于安全库存 → alert
- M-006 轴承6205 库存不足 → alert

---

## 7. 生产管理数据（Phase 5）

### 7.1 工单 (work_orders) — 15 张（全状态覆盖）
| order_no | product | qty | status | route | 关联入库 | 关联领料 |
|:---|:---|:---:|:---|:---|:---:|:---:|
| WO-2026-0701 | 轴承座 | 50 | released | RTE-BEARING | - | MR-0701→ISS-0701 |
| WO-2026-0702 | 法兰盘 | 100 | released | RTE-FLANGE | - | MR-0703→ISS-0703 |
| WO-2026-0703 | 传动轴 | 30 | released | RTE-SHAFT | - | MR-0708 |
| WO-2026-0704 | 轴承座 | 80 | **in_progress** | RTE-BEARING | - | MR-0702→ISS-0702 |
| WO-2026-0705 | 法兰盘 | 60 | **in_progress** | RTE-FLANGE | - | - |
| WO-2026-0706 | 轴承座 | 40 | **in_progress** | RTE-BEARING | - | MR-0705→ISS-0705 |
| WO-2026-0707 | 传动轴 | 20 | **completed** | RTE-SHAFT | 成品入库 | - |
| WO-2026-0708 | 法兰盘 | 50 | **completed** | RTE-FLANGE | 成品入库 | - |
| WO-2026-0709 | 轴承座 | 30 | **completed** | RTE-BEARING | 成品入库 | - |
| WO-2026-0710 | 轴承座 | 60 | **paused** | RTE-BEARING | - | 材料异常 |
| WO-2026-0711 | 法兰盘 | 40 | **cancelled** | RTE-FLANGE | - | 客户取消 |
| WO-2026-0712 | 传动轴 | 25 | released | RTE-SHAFT | - | MR-0707 |
| WO-2026-0713 | 轴承座 | 45 | **in_progress** | RTE-BEARING | - | MR-0704→ISS-0704 |
| WO-2026-0714 | 法兰盘 | 35 | **in_progress** | RTE-FLANGE | - | - |
| WO-2026-0715 | 传动轴 | 15 | **in_progress** | RTE-SHAFT | - | MR-0706→ISS-0706 |

### 7.2 报工记录 (work_reports) — 约 35 条
每张 in_progress/completed 工单的各道已执行工序均有报工。

| 工单 | 已完成工序 | 报工记录数 | 良品率 |
|:---|:---|:---:|:---:|
| WO-0704 (轴承座 80件) | 来料检→粗车→精车→铣削 (4/7序) | 4 | 95% |
| WO-0705 (法兰盘 60件) | 来料检→粗车→精车 (3/7序) | 3 | 97% |
| WO-0706 (轴承座 40件) | 来料检→粗车→精车→铣削→钻孔 (5/7序) | 5 | 93% |
| WO-0707 (传动轴 20件) | 全8序完成 | 8 | 90% |
| WO-0708 (法兰盘 50件) | 全7序完成 | 7 | 96% |
| WO-0709 (轴承座 30件) | 全7序完成 | 7 | 92% |
| WO-0713 (轴承座 45件) | 来料检→粗车→精车→铣削→钻孔→热处理 (6/7序) | 6 | 91% |
| WO-0714 (法兰盘 35件) | 来料检→粗车→精车→铣削 (4/7序) | 4 | 95% |
| WO-0715 (传动轴 15件) | 来料检→粗车→热处理→磨削→钻孔→过程检 (6/8序) | 6 | 88% |

**报工数据字段**：work_order_id, operation_code, report_date, reporter_id, input_qty, output_qty, scrap_qty, defect_reason, labor_hours, machine_hours

### 7.3 BOM 快照 (bom_snapshots)
3 张 completed 工单 (WO-0707/0708/0709) 各有 BOM 快照记录。

### 7.4 工单状态变更日志 (work_order_status_logs)
每张工单从 released → in_progress → (completed/paused/cancelled) 的每次变更记录。

### 7.5 安灯关联
部分 in_progress 工单在报工异常时触发安灯呼叫（详见 §9）。

---

## 8. 品质管理数据（Phase 6）

### 8.1 检验标准 (inspection_standard) — 6 条
| name | standard_type | 适用产品/工序 |
|:---|:---|:---|
| 轴承座来料检验标准 | incoming | PRO-001, OP-0010 |
| 轴承座过程检验标准 | process | PRO-001, OP-0080 |
| 轴承座成品检验标准 | final | PRO-001, OP-0100 |
| 法兰盘来料检验标准 | incoming | PRO-002, OP-0010 |
| 法兰盘过程检验标准 | process | PRO-002, OP-0080 |
| 传动轴成品检验标准 | final | PRO-003, OP-0100 |

### 8.2 检验记录 (inspection_order + inspection_result) — 约 20 条
每张工单在 QC 工序（来料/过程/成品）都有对应检验记录，含具体检测项和实测值。

### 8.3 QC 点配置 (qc_point_config) — 6 个
在工艺路线的 QC 工序位置配置抽样方案：
| point_name | point_type | process | sampling_plan | 频次 |
|:---|:---|:---|:---|:---:|
| 轴承座来料检 | incoming | OP-0010 | 100%全检 | 每批 |
| 轴承座精车SPC | process | OP-0030 | n=5 | 每2h |
| 轴承座钻孔SPC | process | OP-0050 | n=3 | 每班 |
| 法兰盘精车SPC | process | OP-0030 | n=5 | 每2h |
| 轴热处理检验 | process | OP-0060 | 100%硬度 | 每炉 |
| 传动轴磨削SPC | process | OP-0070 | n=5 | 每3h |

### 8.4 SPC 控制限 (spc_control_limits) + 数据点
| dimension_key | chart_type | cl | ucl | lcl | data_points |
|:---|:---|:---:|:---:|:---:|:---:|
| 轴承座精车外径 | xbar-r | 199.98 | 200.03 | 199.93 | 20点 |
| 法兰盘厚度 | xbar-r | 25.00 | 25.08 | 24.92 | 15点 |
| 传动轴硬度HRC | xbar-r | 50.0 | 51.5 | 48.5 | 12点 |

### 8.5 FMEA — 3 个文档
- **DFMEA-001**: 轴承座铸造缺陷分析（针对 M-002 毛坯）
- **PFMEA-001**: 轴承座机加工过程 FMEA（高风险项：外径超差 S=7,O=3,D=4,RPN=84）
- **PFMEA-002**: 传动轴热处理 FMEA（高风险项：淬火裂纹 S=9,O=2,D=5,RPN=90）

### 8.6 PPAP — 3 个提交记录
| submission_no | product | customer_id | level | status |
|:---|:---|:---:|:---:|:---|
| PPAP-2026-001 | 轴承座 PRO-001 | 1(重庆通用) | 3 | approved |
| PPAP-2026-002 | 法兰盘 PRO-002 | 1(重庆通用) | 3 | submitted |
| PPAP-2026-003 | 传动轴 PRO-003 | 2(成都精密) | 3 | in_review |

---

## 9. 设备/安灯/能碳数据

### 9.1 保养计划 (maintenance_plans) — 6 个（同 v1）

### 9.2 保养任务 (maintenance_tasks) — 10 条
覆盖已过期、进行中、已完成三种状态，关联具体设备。

### 9.3 安灯呼叫 (andon_call) — 8 条（同 v1 但补充工单关联）
| call_no | type | source | equipment | work_order | status | 响应记录 |
|:---|:---|:---|:---:|:---:|:---|:---|
| ANDON-001 | quality | WO-0704 | CMM-001 | WO-2026-0704 | resolved | 已响应+已解决 |
| ANDON-002 | equipment | WO-0705 | LT-002 | WO-2026-0705 | responding | 已响应解决中 |
| ANDON-003 | material | WO-0710 | WH-RAW | WO-2026-0710 | open | 等待处理 |
| ANDON-004 | quality | WO-0713 | HT-001 | WO-2026-0713 | resolved | 已响应+已解决 |
| ANDON-005 | equipment | WO-0706 | ML-001 | WO-2026-0706 | open | 等待换刀 |
| ANDON-006 | safety | M02工厂 | WC-ASM | - | resolved | 已解决(漏油处理) |
| ANDON-007 | quality | WO-0714 | WC-LATHE | WO-2026-0714 | escalated | 已升级到主管 |
| ANDON-008 | other | WO-0715 | WC-ASM | WO-2026-0715 | open | 缺标准件 |

### 9.4 安灯升级规则 (andon_escalation_rules) — 3 条
| rule_name | call_type | priority | level | timeout_min | notify_role |
|:---|:---|:---:|:---:|:---:|:---|
| 品质异常升级 | quality | high | 1 | 5 | team_leader |
| 品质异常升级 | quality | high | 2 | 10 | department_head |
| 设备故障升级 | equipment | high | 1 | 5 | maintenance_tech |

### 9.5 能碳设备 (energy_device) — 6 个（同 v1）
含 7 天连续碳排放记录 (carbon_emission_record) + 2 条能耗告警 (energy_alert)。
能耗数据按小时粒度，展示峰谷差异。

---

## 10. 实验室/试产/数据采集

### 10.1 实验委托 (lab_requests) — 4 条
| request_no | title | type | source | status | 结论 |
|:---|:---|:---|:---|:---:|:---|
| LAB-2026-001 | 45#钢拉伸试验 | tensile_test | WO-0707 来料 | completed | 合格 |
| LAB-2026-002 | 轴承座热处理后硬度检测 | hardness_test | WO-0713 | completed | 合格 |
| LAB-2026-003 | 传动轴金相分析 | metallographic | WO-0715 | in_progress | - |
| LAB-2026-004 | 法兰盘材料成分分析 | composition | WO-0714 | pending | - |

### 10.2 试产工单 (trial_orders) — 2 条
| order_no | product_name | qty | status | route |
|:---|:---|:---:|:---|:---|
| TRIAL-2026-001 | 新零件-定位套 | 10 | in_progress | 借用RTE-BEARING |
| TRIAL-2026-002 | 新零件-隔套 | 5 | draft | 自定义路线 |

### 10.3 数据采集 (collect_task + collect_data_record)
- 采集任务-1: VMC850 主轴振动监测（每30s采集）
- 采集任务-2: 热处理炉温曲线（每60s采集）
- 各产生 24h 模拟数据点

---

## 11. 数据清理与写入策略

### 保留数据（不删除）
| 表 | 说明 |
|:---|:---|
| users | 10 个测试用户 |
| roles | 9 个角色（admin, department_head 等） |
| user_roles | 用户-角色关联 |
| tenants | mfg_demo 租户 |
| change_log | 同步基础设施 |
| sync_consumer | 同步消费者 |
| alembic_version | 迁移版本 |

### 清除数据（TRUNCATE CASCADE）
所有其他业务表，按外键依赖倒序 TRUNCATE。

### 写入顺序
```
Phase 0: TRUNCATE（全部业务数据）
Phase 1: 基础数据（operations → work_centers → equipment_categories → equipment → employees → teams → wc_equipments）
Phase 2: 产品/BOM/工艺（products → product_versions → materials → product_bom → process_routes → route_steps → product_routes）
Phase 3: 工厂日历（factory_calendars — 2026年7-12月）
Phase 4: 仓库（warehouses → warehouse_zones → warehouse_locations）
Phase 5: 物料（batches → inventory → inventory_items → inventory_alerts）
Phase 6: 采购入库（receipt_orders → receipt_order_items）
Phase 7: 生产（work_orders → work_order_status_logs）
Phase 8: 领料出库（material_requests → material_request_items → issue_orders → issue_order_items → inventory_transactions）
Phase 9: 报工（work_reports → bom_snapshots）
Phase 10: 品质（inspection_standard → qc_point_config → inspection_order → inspection_result → spc_control_limits → spc_data_points）
Phase 11: FMEA/PPAP（fmea_documents → fmea_items/fmea_hierarchies/fmea_actions → control_plans → ppap_levels → ppap_submissions → ppap_submission_items）
Phase 12: 保养（maintenance_plans → maintenance_tasks）
Phase 13: 安灯（andon_escalation_rules → andon_call → andon_response → andon_escalation_logs）
Phase 14: 能碳（energy_device → energy_alert → carbon_emission_record → collect_task → collect_data_record）
Phase 15: 实验室/试产（lab_requests → lab_test_results → trial_orders → trial_bom → trial_routes）
Phase 16: 质量报告 → 生产快照
Phase 17: 字典/日历辅助数据
```

---

## 12. 预期效果

写入后 `mfg1.ziwi.cn` 全模块可使用状态：

| 模块 | 页面 | 可看到的数据 |
|:---|:---|:---|
| 🏠 驾驶舱 | 生产概要 | 15工单、完成率47%、异常数3、能耗趋势 |
| 📦 基础数据 | 物料/产品/BOM | 9物料+3产品+3BOM |
| 📦 基础数据 | 工序/工艺路线 | 10工序+6工作中心+3工艺路线 |
| 📦 基础数据 | 设备台账 | 12台设备(含运行/停机/保养状态) |
| 🏭 生产管理 | 工单管理 | 15张工单(5 released/6 in_progress/3 completed/1 paused/1 cancelled) |
| 🏭 生产管理 | 报工管理 | 35条报工记录，覆盖各工单每道工序 |
| 🏭 生产管理 | 生产排产 | 有排产数据可查看 |
| 📋 品质管理 | 检验记录 | 20条检验记录(来料/过程/成品) |
| 📋 品质管理 | SPC 控制图 | 3个维度×15-20个数据点 |
| 📋 品质管理 | PPAP/FMEA | 3 PPAP + 3 FMEA 文档 |
| 🔧 设备管理 | 保养计划/任务 | 6计划+10任务 |
| 🚨 安灯管理 | 安灯面板 | 8呼叫(3已解决/3待处理/1响应中/1已升级) |
| ⚡ 能碳管理 | 设备/告警/碳排 | 6设备+7天碳排+2告警 |
| 📦 仓库管理 | 库存/出入库 | 3仓+20库位+9物料库存+6入库单+6出库单 |
| 📦 仓库管理 | 库存流水 | 20+ inventory_transactions 记录 |
| 📦 仓库管理 | 库存预警 | 2条低库存告警 |
| 📦 仓库管理 | 盘点 | 1条盘点任务 |
| 🔬 实验室 | 委托/报告 | 4委托(2完成/1进行中/1待处理) |
| 🧪 试产管理 | 试产工单 | 2条(进行中/草稿) |
| 📊 数据采集 | 采集任务 | 2任务+48h模拟数据 |
| 📋 系统设置 | 审批/消息/字典 | 辅助数据完备 |

### 数据留痕验证表（你可以在各页面查到）
| 数据维度 | 查什么 | 期望值 |
|:---|:---|:---:|
| 供应商交付记录 | 收货单列表 | 6条(intransit/completed) |
| 批次追溯 | 批次B20260701的库存 | 45#圆钢 200根 |
| 物料流转全景 |  inventory_transactions | 原料入→出→半成品→成品 |
| BOM齐套检查 | product_bom 条目 | 3产品合计14行BOM |
| 工单-报工关联 | 某工单详情→报工列表 | 每道工序都有报工 |
| 工单-安灯关联 | 工单异常→安灯记录 | 异常工单触发安灯 |
| 工单-品质关联 | 工单→检验记录 | QC工序自动产生检验 |
| 设备-保养关联 | 设备详情→保养任务 | 保养到期提醒 |
| 设备-能碳关联 | 设备→能耗数据 | 运行设备有能耗记录 |

---

以上是 v2.0 完整规划。确认后我：
1. 编写完整 seed 脚本（约 600-800 行 Python）
2. 远程部署：清旧数据 → 写入全套仿真数据
3. 跑 Playwright 全流程验证
4. 生成 Buglist 报告
