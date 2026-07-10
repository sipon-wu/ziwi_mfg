"""回归测试：验证 mfg 心跳客户端在应用启动/关闭时真正启动与停止。

本文件是临时冒烟脚本 ``backend/_smoke_heartbeat.py`` 的正式化版本，使验证可重复。

包含两组测试：
  A) ``test_heartbeat_lifespan_via_factory`` —— 用最小 FastAPI app 直接挂载
     ``create_heartbeat_lifespan(config=...)``，验证「工厂 + __aenter__/__aexit__」机制。
     该测试【不依赖 app.main / app.core.config.Settings】，当前即可运行（绿）。
  B) ``test_heartbeat_lifespan_via_app_main`` —— 通过 app.main 的真实 lifespan 端到端验证
     启动/停止（真实代码路径）。Round 2 已确认 app.core.config.Settings 已含
     extra="ignore"、HeartbeatClientConfig 已含 env_ignore_empty=True，故该用例直接运行。

说明：本测试通过 monkeypatch 桩替换 send_once/stop，不发起任何真实网络请求。
``stop`` 桩在计数后会调用【真实】 stop，以关闭 APScheduler 后台线程，避免进程挂起
（原冒烟脚本的 fake_stop 为同步函数，而 stop 是 async 且经 await 调用，会导致真实
scheduler 未被关闭、进程卡死——此处已修正）。

运行（backend 目录下）：
    .venv/Scripts/python.exe -m pytest tests/test_heartbeat_lifespan.py -v
"""

import os
import sys

# 确保 backend 根目录在 sys.path，使 `app` 与 `heartbeat_client` 可导入
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(HERE)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import heartbeat_client.heartbeat_client as hb_mod
from heartbeat_client import create_heartbeat_lifespan, HeartbeatClientConfig


def _install_stubs(monkeypatch):
    """用计数桩替换 send_once/stop；stop 桩在计数后调用真实 stop 以关闭 scheduler。"""
    stats = {"send_once": 0, "stop": 0}
    orig_stop = hb_mod.HeartbeatClient.stop

    async def fake_send_once(self):
        stats["send_once"] += 1
        return {"status": "created", "deployment_id": self._deployment_id}

    async def fake_stop(self):
        stats["stop"] += 1
        # 调用真实 stop 以真正关闭 BackgroundScheduler，避免进程挂起
        return await orig_stop(self)

    monkeypatch.setattr(hb_mod.HeartbeatClient, "send_once", fake_send_once)
    monkeypatch.setattr(hb_mod.HeartbeatClient, "stop", fake_stop)
    return stats


@pytest.fixture
def patched_heartbeat(monkeypatch):
    return _install_stubs(monkeypatch)


# ---------------------------------------------------------------------------
# A) 工厂机制（不依赖 app.main，当前即绿）
# ---------------------------------------------------------------------------
def test_heartbeat_lifespan_via_factory(patched_heartbeat):
    """验证 create_heartbeat_lifespan 工厂 + __aenter__/__aexit__ 正确启动/停止。"""
    cfg = HeartbeatClientConfig(
        api_key="fake-dev-key-for-smoke",
        deployment_id="smoke-deploy-001",
        tenant_id="mfg_smoke",
        product="mfg",
        interval_seconds=3600,
        license_issued_at=None,
        license_expires_at=None,
    )
    app = FastAPI(lifespan=create_heartbeat_lifespan(config=cfg))
    with TestClient(app):
        # 启动期执行 __aenter__ -> client.start -> send_once
        pass
    assert patched_heartbeat["send_once"] >= 1, "send_once 未被调用 -> 心跳未启动"
    assert patched_heartbeat["stop"] >= 1, "stop 未被调用 -> 关闭时未停止心跳"


# ---------------------------------------------------------------------------
# B) 真实 app.main lifespan（端到端；需源码修复后通过，当前自动 skip）
# ---------------------------------------------------------------------------
def test_heartbeat_lifespan_via_app_main(patched_heartbeat, monkeypatch):
    """验证 app.main 真实 lifespan 在启动时发送首心跳、关闭时停止。

    前置：APP_ENV=smoke + 伪 HEARTBEAT_API_KEY/DEPLOYMENT_ID 触发守卫。
    依赖源码修复（见 QA 报告）：
      - app.core.config.Settings 需 extra="ignore"
      - HeartbeatClientConfig 需 env_ignore_empty=True
    """
    monkeypatch.setenv("APP_ENV", "smoke")
    monkeypatch.setenv("HEARTBEAT_API_KEY", "fake-dev-key-for-smoke")
    monkeypatch.setenv("HEARTBEAT_DEPLOYMENT_ID", "smoke-deploy-001")
    monkeypatch.setenv("HEARTBEAT_TENANT_ID", "mfg_smoke")
    monkeypatch.setenv("HEARTBEAT_PRODUCT", "mfg")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "3600")

    # 清除 get_settings 缓存，使上面的环境变量生效
    import app.core.config as _app_config

    _app_config.get_settings.cache_clear()

    from app.main import app  # 触发真实 lifespan 代码路径

    with TestClient(app):
        pass
    assert patched_heartbeat["send_once"] >= 1, "send_once 未被调用 -> 心跳未启动"
    assert patched_heartbeat["stop"] >= 1, "stop 未被调用 -> 关闭时未停止心跳"
