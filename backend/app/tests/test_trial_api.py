"""M16 试产管理 (NPI) — API 测试"""

import pytest
from datetime import date
from unittest.mock import patch


class TestM16Trial:
    """试产管理 API 测试"""

    # ── 基础 CRUD ──────────────────────────────────────────────

    async def test_create_trial_order(self, async_client):
        """M16-02: 创建试产工单（new_product）"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_max_order_no") as mock_max,
            patch("app.repositories.trial_repo.TrialOrderRepository.create_order") as mock_create,
        ):
            mock_max.return_value = None
            mock_create.return_value = 1
            resp = await async_client.post("/api/v1/trials", json={
                "trial_type": "new_product",
                "product_name": "测试产品A",
                "product_id": 1,
                "planned_qty": 100,
                "priority": 500,
                "scheme_json": {"key": "value"},
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 1
        assert "NP-" in data["data"]["order_no"]

    async def test_create_trial_order_new_process(self, async_client):
        """M16-02: 创建新工艺试产工单"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_max_order_no") as mock_max,
            patch("app.repositories.trial_repo.TrialOrderRepository.create_order") as mock_create,
        ):
            mock_max.return_value = "NP-202606-0005"
            mock_create.return_value = 2
            resp = await async_client.post("/api/v1/trials", json={
                "trial_type": "new_process",
                "product_name": "测试工艺B",
                "product_id": 2,
                "planned_qty": 50,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 2
        # 服务按当前月生成前缀 (trial_service.py: prefix = NP-%Y%m-)
        # mock 返回 6 月序号 0005 → 提取 seq=5 → 自增为 6，但前缀用当前月
        today_prefix = f"NP-{date.today().strftime('%Y%m')}-"
        assert data["data"]["order_no"] == f"{today_prefix}0006"

    async def test_list_trials(self, async_client):
        """M16-01: 列出试产工单"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.list_orders") as mock:
            mock.return_value = {
                "items": [
                    {"id": 1, "order_no": "NP-202606-0001", "trial_type": "new_product",
                     "status": "planning", "product_name": "产品A", "planned_qty": 100},
                    {"id": 2, "order_no": "NP-202606-0002", "trial_type": "new_process",
                     "status": "lab_trial", "product_name": "产品B", "planned_qty": 50},
                ],
                "total": 2, "page": 1, "page_size": 20,
            }
            resp = await async_client.get("/api/v1/trials?page=1&page_size=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["items"]) == 2
        assert data["data"]["total"] == 2

    async def test_list_trials_filtered(self, async_client):
        """M16-01: 按类型和状态筛选"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.list_orders") as mock:
            mock.return_value = {
                "items": [
                    {"id": 3, "trial_type": "new_material", "status": "planning",
                     "product_name": "材料C", "planned_qty": 200},
                ],
                "total": 1, "page": 1, "page_size": 20,
            }
            resp = await async_client.get(
                "/api/v1/trials?trial_type=new_material&status=planning&page=1&page_size=20"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["trial_type"] == "new_material"

    async def test_get_trial_detail(self, async_client):
        """获取试产工单详情"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = {
                "id": 1, "order_no": "NP-202606-0001", "trial_type": "new_product",
                "status": "planning", "product_id": 1, "product_name": "产品A",
                "planned_qty": 100, "priority": 500,
                "scheme_json": '{"key": "value"}',
            }
            resp = await async_client.get("/api/v1/trials/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 1
        assert data["data"]["product_name"] == "产品A"
        # JSON 字段应反序列化
        assert isinstance(data["data"]["scheme_json"], dict)

    async def test_get_trial_not_found(self, async_client):
        """查询不存在的试产工单应返回 404"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = None
            resp = await async_client.get("/api/v1/trials/999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "404-0000"

    # ── 编辑 ─────────────────────────────────────────────────

    async def test_update_trial_planning(self, async_client):
        """编辑试产工单（规划阶段可编辑全部字段）"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_get.return_value = {
                "id": 1, "status": "planning", "trial_type": "new_product",
                "product_name": "产品A",
            }
            mock_upd.return_value = 1
            resp = await async_client.put("/api/v1/trials/1", json={
                "product_name": "产品A-修改",
                "planned_qty": 200,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        # 验证 update_order 被调用且包含修改后的字段
        call_data = mock_upd.call_args[0][1]
        assert call_data["product_name"] == "产品A-修改"
        assert call_data["planned_qty"] == 200

    async def test_update_trial_not_planning(self, async_client):
        """非规划阶段仅允许编辑 terminated_reason"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_get.return_value = {
                "id": 1, "status": "lab_trial", "trial_type": "new_product",
                "product_name": "产品A",
            }
            mock_upd.return_value = 1
            resp = await async_client.put("/api/v1/trials/1", json={
                "product_name": "不应生效",
                "terminated_reason": "需要终止",
            })
        assert resp.status_code == 200
        call_data = mock_upd.call_args[0][1]
        # 只允许 terminated_reason，不能修改 product_name
        assert "product_name" not in call_data
        assert call_data["terminated_reason"] == "需要终止"

    async def test_update_trial_not_found(self, async_client):
        """更新不存在的试产工单应返回 404"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = None
            resp = await async_client.put("/api/v1/trials/999", json={"product_name": "不存在"})
        assert resp.status_code == 404

    # ── 状态机 ───────────────────────────────────────────────

    async def test_advance_stage_normal(self, async_client):
        """M16-05: new_product planning → lab_trial 阶段推进"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_get.side_effect = [
                {"id": 1, "trial_type": "new_product", "status": "planning"},
                {"id": 1, "trial_type": "new_product", "status": "lab_trial"},
            ]
            mock_upd.return_value = 1
            resp = await async_client.post("/api/v1/trials/1/advance", json={
                "target_stage": "lab_trial",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "lab_trial" in data["message"]

    async def test_advance_stage_skip_lab_trial(self, async_client):
        """new_process 跳过 lab_trial: planning → pilot_run"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_get.side_effect = [
                {"id": 2, "trial_type": "new_process", "status": "planning"},
                {"id": 2, "trial_type": "new_process", "status": "pilot_run"},
            ]
            mock_upd.return_value = 1
            resp = await async_client.post("/api/v1/trials/2/advance", json={
                "target_stage": "pilot_run",
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_advance_stage_skip_pilot_run(self, async_client):
        """new_material 跳过 pilot_run: lab_trial → batch_verify"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_get.side_effect = [
                {"id": 3, "trial_type": "new_material", "status": "lab_trial"},
                {"id": 3, "trial_type": "new_material", "status": "batch_verify"},
            ]
            mock_upd.return_value = 1
            resp = await async_client.post("/api/v1/trials/3/advance", json={
                "target_stage": "batch_verify",
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_advance_stage_terminated_error(self, async_client):
        """已终止的试产无法推进"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = {
                "id": 4, "trial_type": "new_product", "status": "terminated",
            }
            resp = await async_client.post("/api/v1/trials/4/advance", json={
                "target_stage": "lab_trial",
            })
        assert resp.status_code == 400
        assert "终态" in resp.json()["detail"]["message"]

    async def test_advance_stage_no_skip_middle(self, async_client):
        """不能跳过不可跳过的中间阶段"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = {
                "id": 5, "trial_type": "new_product", "status": "planning",
            }
            # new_product 不能跳过 lab_trial，直接到 pilot_run 应报错
            resp = await async_client.post("/api/v1/trials/5/advance", json={
                "target_stage": "pilot_run",
            })
        assert resp.status_code == 400

    # ── BOM 管理 ─────────────────────────────────────────────

    async def test_save_trial_bom_new(self, async_client):
        """M16-03: 保存试产BOM（新建）"""
        with (
            patch("app.repositories.trial_repo.TrialBomRepository.get_by_order") as mock_get,
            patch("app.repositories.trial_repo.TrialBomRepository.create_bom") as mock_create,
        ):
            mock_get.return_value = None
            mock_create.return_value = 1
            resp = await async_client.put("/api/v1/trials/1/bom", json={
                "bom_json": [{"material_code": "M001", "qty": 10}],
                "source_type": "manual",
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["message"] == "试产BOM已保存"

    async def test_save_trial_bom_update(self, async_client):
        """M16-03: 更新已存在的试产BOM"""
        with (
            patch("app.repositories.trial_repo.TrialBomRepository.get_by_order") as mock_get,
            patch("app.repositories.trial_repo.TrialBomRepository.update_bom") as mock_upd,
        ):
            mock_get.return_value = {"id": 10, "trial_order_id": 1, "bom_json": "[]"}
            mock_upd.return_value = 1
            resp = await async_client.put("/api/v1/trials/1/bom", json={
                "bom_json": [{"material_code": "M002", "qty": 20}],
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_get_trial_bom(self, async_client):
        """M16-03: 获取试产BOM"""
        with patch("app.repositories.trial_repo.TrialBomRepository.get_by_order") as mock:
            mock.return_value = {
                "id": 10, "trial_order_id": 1,
                "bom_json": '[{"material_code": "M001", "qty": 10}]',
                "source_type": "manual",
            }
            resp = await async_client.get("/api/v1/trials/1/bom")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"]["bom_json"], list)

    async def test_get_trial_bom_not_found(self, async_client):
        """获取不存在的试产BOM返回空对象"""
        with patch("app.repositories.trial_repo.TrialBomRepository.get_by_order") as mock:
            mock.return_value = None
            resp = await async_client.get("/api/v1/trials/999/bom")
        assert resp.status_code == 200
        assert resp.json()["data"] == {}

    # ── 路线管理 ─────────────────────────────────────────────

    async def test_save_trial_route_new(self, async_client):
        """M16-04: 保存试产路线（新建）"""
        with (
            patch("app.repositories.trial_repo.TrialRouteRepository.get_by_order") as mock_get,
            patch("app.repositories.trial_repo.TrialRouteRepository.create_route") as mock_create,
        ):
            mock_get.return_value = None
            mock_create.return_value = 1
            resp = await async_client.put("/api/v1/trials/1/routes", json={
                "route_json": [{"工序": "下料", "设备": "切割机"}],
                "name": "试产路线-001",
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_save_trial_route_update(self, async_client):
        """M16-04: 更新已存在的试产路线"""
        with (
            patch("app.repositories.trial_repo.TrialRouteRepository.get_by_order") as mock_get,
            patch("app.repositories.trial_repo.TrialRouteRepository.update_route") as mock_upd,
        ):
            mock_get.return_value = {"id": 20, "trial_order_id": 1}
            mock_upd.return_value = 1
            resp = await async_client.put("/api/v1/trials/1/routes", json={
                "route_json": [{"工序": "焊接", "设备": "焊机"}],
                "name": "试产路线-002",
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_get_trial_route(self, async_client):
        """M16-04: 获取试产路线"""
        with patch("app.repositories.trial_repo.TrialRouteRepository.get_by_order") as mock:
            mock.return_value = {
                "id": 20, "trial_order_id": 1,
                "route_json": '[{"工序": "下料", "设备": "切割机"}]',
                "name": "试产路线-001",
            }
            resp = await async_client.get("/api/v1/trials/1/routes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"]["route_json"], list)

    # ── 从正式数据载入 ───────────────────────────────────────

    async def test_import_bom_from_formal(self, async_client):
        """从正式BOM载入"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            # import_bom_from_formal 不检查订单是否存在（简化实现），但需要 mock get_order
            # 因为 TrialService 构造函数会创建子 repo，避免内部调用出错
            mock.return_value = {"id": 1}
            resp = await async_client.post("/api/v1/trials/1/import-bom", json={
                "source_id": 5,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "正式BOM" in resp.json()["message"]

    async def test_import_route_from_formal(self, async_client):
        """从正式路线载入"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = {"id": 1}
            resp = await async_client.post("/api/v1/trials/1/import-route", json={
                "source_id": 3,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "正式路线" in resp.json()["message"]

    # ── 评审流程 ─────────────────────────────────────────────

    async def test_submit_review(self, async_client):
        """M16-06: 提交评审"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
            patch("app.repositories.trial_repo.TrialReviewRepository.create_review") as mock_review,
        ):
            mock_get.return_value = {
                "id": 1, "trial_type": "new_product", "status": "batch_verify",
            }
            mock_upd.return_value = 1
            mock_review.return_value = 100
            resp = await async_client.post("/api/v1/trials/1/review", json={
                "review_stage": "batch_verify",
                "review_items": [{"item": "外观检查", "result": "合格"}],
                "summary_data": {"合格率": "98%"},
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 100

    async def test_list_reviews(self, async_client):
        """评审列表"""
        with patch("app.repositories.trial_repo.TrialReviewRepository.list_by_order") as mock:
            mock.return_value = [
                {"id": 100, "trial_order_id": 1, "conclusion": "pending",
                 "review_stage": "batch_verify",
                 "review_items": '[{"item": "外观检查"}]'},
                {"id": 101, "trial_order_id": 1, "conclusion": "approved",
                 "review_stage": "batch_verify",
                 "reviewed_at": "2026-06-20T10:00:00"},
            ]
            resp = await async_client.get("/api/v1/trials/1/reviews")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]) == 2
        # JSON 字段应反序列化
        assert isinstance(data["data"][0]["review_items"], list)

    async def test_make_review_decision_approved(self, async_client):
        """M16-07: 评审决策 — 通过"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_order,
            patch("app.repositories.trial_repo.TrialReviewRepository.get_review") as mock_review,
            patch("app.repositories.trial_repo.TrialReviewRepository.update_review") as mock_upd,
        ):
            mock_order.return_value = {"id": 1, "status": "review"}
            mock_review.return_value = {"id": 100, "trial_order_id": 1}
            mock_upd.return_value = 1
            resp = await async_client.post(
                "/api/v1/trials/1/reviews/100/decide", json={
                    "conclusion": "approved",
                }
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "approved" in resp.json()["message"]

    async def test_make_review_decision_terminated(self, async_client):
        """M16-07: 评审决策 — 终止（同时终止试产）"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_order,
            patch("app.repositories.trial_repo.TrialReviewRepository.get_review") as mock_review,
            patch("app.repositories.trial_repo.TrialReviewRepository.update_review") as mock_upd,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_ord_upd,
        ):
            mock_order.return_value = {"id": 1, "status": "review"}
            mock_review.return_value = {"id": 100, "trial_order_id": 1}
            mock_upd.return_value = 1
            mock_ord_upd.return_value = 1
            resp = await async_client.post(
                "/api/v1/trials/1/reviews/100/decide", json={
                    "conclusion": "terminated",
                    "terminated_reason": "验证不通过",
                }
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    # ── 转量产 & 终止 ────────────────────────────────────────

    async def test_convert_to_production(self, async_client):
        """M16-08: 评审通过后一键转量产"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_order,
            patch("app.repositories.trial_repo.TrialReviewRepository.list_by_order") as mock_reviews,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_order.return_value = {
                "id": 1, "status": "review", "product_id": 1,
                "product_name": "产品A",
            }
            mock_reviews.return_value = [
                {"id": 100, "conclusion": "approved", "reviewed_at": "2026-06-20T10:00:00"},
            ]
            mock_upd.return_value = 1
            resp = await async_client.post("/api/v1/trials/1/convert")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "转量产" in resp.json()["message"]

    async def test_convert_to_production_not_review(self, async_client):
        """非评审阶段不能转量产"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = {
                "id": 1, "status": "planning",
            }
            resp = await async_client.post("/api/v1/trials/1/convert")
        assert resp.status_code == 400
        assert "评审阶段" in resp.json()["detail"]["message"]

    async def test_terminate_trial(self, async_client):
        """M16-09: 终止试产"""
        with (
            patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock_get,
            patch("app.repositories.trial_repo.TrialOrderRepository.update_order") as mock_upd,
        ):
            mock_get.return_value = {
                "id": 1, "trial_type": "new_product", "status": "lab_trial",
            }
            mock_upd.return_value = 1
            resp = await async_client.post("/api/v1/trials/1/terminate", json={
                "conclusion": "terminated",
                "terminated_reason": "客户需求变更",
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_terminate_trial_already_final(self, async_client):
        """已处于终态的试产无法再次终止"""
        with patch("app.repositories.trial_repo.TrialOrderRepository.get_order") as mock:
            mock.return_value = {
                "id": 1, "trial_type": "new_product", "status": "terminated",
            }
            resp = await async_client.post("/api/v1/trials/1/terminate", json={
                "conclusion": "terminated",
                "terminated_reason": "再次终止",
            })
        assert resp.status_code == 400
        assert "终态" in resp.json()["detail"]["message"]
