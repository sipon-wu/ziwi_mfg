"""工序「环」要素（温度/湿度/洁净度）的闸。

## 这条为什么必须有测试

`operations.env_req` 从第一天就被设计成结构化 JSON
（``docs/basic-data-code-plan.md:66``：``{temp_min, temp_max, humidity_min,
humidity_max, clean_level}``），但实现退化成了 ``Optional[str]`` 自由文本，
页面连输入框都没有 —— **全库 233 条工序，0 条有值**。于是
``product-route-capability-model-v2.md`` 的 Tab7「环：无尘度/温度/湿度」
一直是纸面，无尘车间排产、外协判定全都无据可依。

这类"字段存在但没有任何落点"的坑不会报错、不会红，只能靠闸拦。这里钉死四件事：

1. **值域可渲染** —— 派生/录入的每个洁净度码都有中文名（前车之鉴：工艺性质
   借用 `WC_TYPE_LABELS`，结果 `filling` 渲染成「未知（filling）」）
2. **旧自由文本不丢** —— 解析不了的字符串收进 `legacy_text`，而不是当空值抹掉
3. **界面真有输入框** —— 只有类型声明 + `env_req: null` 的"假落点"必须被抓出来
4. **前后端值域逐项同序** —— 两边各写一份，迟早漏一个
"""
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.enums import (
    CLEAN_LEVELS,
    CLEAN_LEVEL_LABELS,
    clean_level_label,
)
from app.core.env_req import (
    ENV_REQ_KEYS,
    LEGACY_KEY,
    decode_env_req,
    encode_env_req,
    flat_clean_level,
)
from app.schemas.basic_data import EnvReq, OperationCreate, OperationUpdate

ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ENUMS = ROOT / "frontend" / "src" / "config" / "enums.ts"
OPERATION_LIST = ROOT / "frontend" / "src" / "pages" / "basics" / "OperationList.vue"
SEARCH_FIELDS = ROOT / "frontend" / "src" / "config" / "searchFields.ts"
ROW_DETAIL = ROOT / "frontend" / "src" / "components" / "ListRowDetail.vue"
UI_ENUM_GATE = ROOT / "scripts" / "check_ui_enum_labels.py"
REPO = ROOT / "backend" / "app" / "repositories" / "basic_data_repo.py"


# ── 1. 值域 ────────────────────────────────────────────────────


class TestCleanLevelDomain:
    def test_every_level_has_a_chinese_label(self):
        for code in CLEAN_LEVELS:
            label = clean_level_label(code)
            assert label, code
            assert "未知" not in label, f"{code} 没有中文名，界面会印「{label}」"
            # 标签里必须带中文，避免有人顺手写成 "ISO 7"
            assert re.search(r"[\u4e00-\u9fff]", label), f"{code} 的标签没有中文：{label}"

    def test_unknown_code_is_marked_not_echoed_as_normal(self):
        """未知值必须显「未知（原文）」。静默回显原文 = 脏数据冒充正常值。"""
        assert clean_level_label("iso4") == "未知（iso4）"
        assert clean_level_label(None) == ""

    def test_no_clean_requirement_is_its_own_value(self):
        """`none`（无洁净要求）≠ 空。前者是"评估过不需要"，后者是"没填"。"""
        assert "none" in CLEAN_LEVELS
        assert clean_level_label("none") != ""

    def test_iso_codes_ascend_with_strictness(self):
        """iso5 最严、iso9 最松：界面上按此顺序排，才不会让人选错。"""
        numeric = [c for c in CLEAN_LEVELS if c.startswith("iso")]
        assert numeric == ["iso5", "iso6", "iso7", "iso8", "iso9"]


# ── 2. 编解码 ──────────────────────────────────────────────────


class TestEnvReqCodec:
    def test_empty_is_none_not_braces(self):
        assert encode_env_req(None) is None
        assert encode_env_req({}) is None
        assert encode_env_req("") is None
        assert encode_env_req("   ") is None
        assert encode_env_req({k: None for k in ENV_REQ_KEYS}) is None

    def test_roundtrip_keeps_values(self):
        src = {
            "clean_level": "iso8",
            "temp_min": 20.0,
            "temp_max": 26.0,
            "humidity_min": 45.0,
            "humidity_max": 60.0,
        }
        stored = encode_env_req(src)
        assert isinstance(stored, str)
        assert decode_env_req(stored) == src

    def test_legacy_free_text_is_never_dropped(self):
        """别的租户/旧前端往里写过自由文本 —— 读一次就把数据抹掉是不可接受的。"""
        stored = encode_env_req("温控 20-25℃，湿度≤60%")
        assert decode_env_req(stored) == {LEGACY_KEY: "温控 20-25℃，湿度≤60%"}
        # 库里已有的裸文本（不是 JSON）也一样收进 legacy_text
        assert decode_env_req("恒温恒湿") == {LEGACY_KEY: "恒温恒湿"}

    def test_non_dict_json_is_also_kept(self):
        assert decode_env_req("[1,2]") == {LEGACY_KEY: "[1,2]"}
        assert decode_env_req("42") == {LEGACY_KEY: "42"}

    def test_unknown_keys_survive_a_read(self):
        """前向兼容：别人写了我们不认识的键，读的时候不能替它删。"""
        stored = '{"clean_level": "iso7", "particle_limit": "352000"}'
        assert decode_env_req(stored)["particle_limit"] == "352000"

    def test_business_keys_only_on_write(self):
        """写入时丢掉野键，但保留 legacy_text。"""
        stored = encode_env_req({"clean_level": "iso7", "junk": 1})
        assert decode_env_req(stored) == {"clean_level": "iso7"}

    def test_flat_clean_level_is_the_search_handle(self):
        assert flat_clean_level({"clean_level": "iso8"}) == "iso8"
        assert flat_clean_level({"clean_level": ""}) is None
        assert flat_clean_level(None) is None
        assert flat_clean_level({}) is None


# ── 3. 校验 ────────────────────────────────────────────────────


class TestEnvReqValidation:
    def test_string_input_is_decoded(self):
        model = EnvReq.model_validate('{"clean_level": "iso8"}')
        assert model.clean_level == "iso8"

    def test_illegal_clean_level_is_rejected(self):
        with pytest.raises(ValidationError):
            EnvReq.model_validate({"clean_level": "万级"})

    def test_temperature_range_must_be_ordered(self):
        with pytest.raises(ValidationError, match="温度下限"):
            EnvReq.model_validate({"temp_min": 30, "temp_max": 20})

    def test_humidity_range_must_be_ordered(self):
        with pytest.raises(ValidationError, match="湿度下限"):
            EnvReq.model_validate({"humidity_min": 60, "humidity_max": 40})

    def test_humidity_is_bounded_to_percent(self):
        """0~100 之外直接拒：120 是忘了换算，-5 是手滑。

        注意**不拦** `0.45` 这种"小数当百分数"的写法 —— 它确实落在合法区间里，
        硬拦等于替客户判定"湿度不能低于 1%RH"，而超干间就是这么写的。
        这类单位混淆交给界面提示（`op-env-hint` 写明"填 0~100 的百分数"）。
        """
        with pytest.raises(ValidationError, match="0~100"):
            EnvReq.model_validate({"humidity_max": 120})
        with pytest.raises(ValidationError, match="0~100"):
            EnvReq.model_validate({"humidity_min": -5})
        assert EnvReq.model_validate({"humidity_min": 0.45}).humidity_min == 0.45

    def test_partial_input_is_allowed(self):
        """只填洁净度、温湿度留空是合法状态（客户就是只给了洁净度）。"""
        model = EnvReq.model_validate({"clean_level": "iso8"})
        assert model.temp_min is None


# ── 4. schema 形状（不许退回 str） ─────────────────────────────


class TestSchemaShape:
    def test_env_req_is_structured_on_all_three_schemas(self):
        for cls in (OperationCreate, OperationUpdate):
            ann = str(cls.model_fields["env_req"].annotation)
            assert "EnvReq" in ann, f"{cls.__name__}.env_req 又退回自由文本了：{ann}"

    def test_create_dumps_a_dict_not_a_string(self):
        req = OperationCreate(
            code="OP-T1",
            name="贴片",
            op_type="machining",
            env_req={"clean_level": "iso8"},
        )
        dumped = req.model_dump()["env_req"]
        assert isinstance(dumped, dict)
        assert dumped["clean_level"] == "iso8"


# ── 5. 仓储：读解 / 写编 ──────────────────────────────────────


class TestRepositoryWiring:
    def test_reads_are_shaped(self):
        text = REPO.read_text(encoding="utf-8")
        assert "shape_operation(row)" in text
        assert "return shape_operation(await self.query_one(" in text
        # 两个 SELECT * 出口都必须经过 shaping，逐出口各写一遍迟早漏一个
        assert text.count("SELECT * FROM operations") == 2

    def test_writes_are_encoded(self):
        text = REPO.read_text(encoding="utf-8")
        assert 'data["env_req"] = encode_env_req(data.get("env_req"))' in text
        assert 'if "env_req" in data:' in text


# ── 6. 前端：真有输入框 + 不许裸渲染 ───────────────────────────


class TestFrontendLanding:
    def test_frontend_domain_matches_backend_exactly(self):
        text = FRONTEND_ENUMS.read_text(encoding="utf-8")
        block = re.search(
            r"CLEAN_LEVEL_OPTIONS[^=]*=\s*\[(.*?)\n\]", text, re.S
        )
        assert block, "frontend/src/config/enums.ts 里没有 CLEAN_LEVEL_OPTIONS"
        pairs = re.findall(
            r"\{\s*value:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'\s*\}", block.group(1)
        )
        assert [p[0] for p in pairs] == list(CLEAN_LEVELS), (
            "前后端洁净度值域不同步（值或顺序不一致）"
        )
        assert [p[1] for p in pairs] == [CLEAN_LEVEL_LABELS[c] for c in CLEAN_LEVELS]

    def test_operation_form_actually_has_the_inputs(self):
        """★ 这条抓的是"假落点"：类型声明写了、`env_req: null` 初值也写了，
        但表单里一个输入框都没有 —— 上一版就是这样，字段躺着三周没人发现。
        """
        text = OPERATION_LIST.read_text(encoding="utf-8")
        for field in ("clean_level", "temp_min", "temp_max",
                      "humidity_min", "humidity_max"):
            assert f'envForm.{field}' in text, f"工序表单少了 {field} 的录入控件"
        assert "洁净度" in text

    def test_list_does_not_bare_render_the_code(self):
        text = OPERATION_LIST.read_text(encoding="utf-8")
        assert "{{ item.clean_level }}" not in text
        assert "cleanLevelLabel(" in text

    def test_search_config_offers_clean_level(self):
        text = SEARCH_FIELDS.read_text(encoding="utf-8")
        assert re.search(
            r"key:\s*'clean_level'[^}]*type:\s*'enum'", text
        ), "工序高级检索里没有洁净度（enum）条件"

    def test_row_detail_renders_env_req_as_text_not_json(self):
        text = SEARCH_FIELDS.read_text(encoding="utf-8")
        assert re.search(
            r"key:\s*'env_req'[^}]*format:\s*'env-spec'", text
        ), "env_req 仍按 string 渲染 → 详情里会直接吐 JSON"
        detail = ROW_DETAIL.read_text(encoding="utf-8")
        assert "env-spec" in detail and "formatEnvSpec" in detail

    def test_ui_enum_gate_knows_clean_level(self):
        """闸不认识这个字段名，`{{ item.clean_level }}` 就能大摇大摆过闸。"""
        text = UI_ENUM_GATE.read_text(encoding="utf-8")
        assert '"clean_level"' in text
