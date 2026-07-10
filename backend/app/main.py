# FastAPI 应用入口
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uuid

from app.core.config import get_settings
from app.core.database import init_db, ensure_engine
from app.core.scheduler import init_scheduler, start_scheduler, shutdown_scheduler
from heartbeat_client import create_heartbeat_lifespan, HeartbeatClientConfig
from app.api import auth, tenants, users, roles, excel_import, production, dictionary, messages, approvals, organization, tpm, quality, andon, energy, sync, data_collection, bom, spc, ppap, fmea, basic_data, wms, trial, lab, system

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    try:
        await init_db()
    except Exception as e:
        print(f"[WARN] 数据库连接失败: {e}，应用以无DB模式启动")

    # 初始化并启动 APScheduler
    try:
        init_scheduler()
        start_scheduler()
        print("[INFO] APScheduler 定时任务已启动")
    except Exception as e:
        print(f"[WARN] APScheduler 初始化失败: {e}")

    # 启动私有部署心跳上报（heartbeat.ziwi.cn，接口契约 D.1 节）
    # 仅当 HEARTBEAT_API_KEY 与 HEARTBEAT_DEPLOYMENT_ID 均已配置且非测试环境时启用，
    # 避免测试/未配置环境发起真实网络请求。心跳失败不影响应用启动（降级原则）。
    heartbeat_ctx = None
    try:
        hb_config = HeartbeatClientConfig()
        if hb_config.api_key and hb_config.deployment_id and settings.APP_ENV != "test":
            # create_heartbeat_lifespan 返回工厂函数 _lifespan(app)；
            # 必须先调用工厂得到真正的 async context manager，再 __aenter__
            hb_factory = create_heartbeat_lifespan(config=hb_config)
            heartbeat_ctx = hb_factory(app)
            await heartbeat_ctx.__aenter__()
            print("[INFO] 心跳上报客户端已启动")
        else:
            print("[INFO] 心跳上报未启用（缺少 HEARTBEAT_API_KEY / HEARTBEAT_DEPLOYMENT_ID，或处于测试环境）")
    except Exception as e:
        print(f"[WARN] 心跳上报启动失败（不影响应用）: {e}")

    yield

    # 关闭时
    if heartbeat_ctx is not None:
        try:
            await heartbeat_ctx.__aexit__(None, None, None)
        except Exception:
            pass
    try:
        shutdown_scheduler()
    except Exception:
        pass
    try:
        await ensure_engine().dispose()
    except Exception:
        pass

app = FastAPI(
    title="知微 ziwi SaaS API",
    description="知微(SaaS)平台 — Phase 1 核心业务 API",
    version="1.0.0",
    lifespan=lifespan,
    debug=settings.IS_DEBUG,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(excel_import.router)
app.include_router(production.router)
app.include_router(dictionary.router)
app.include_router(messages.router)
app.include_router(approvals.router)
app.include_router(organization.router)
app.include_router(tpm.router)
app.include_router(quality.router)
app.include_router(andon.router)
app.include_router(energy.router)
app.include_router(sync.router)
app.include_router(data_collection.router)
app.include_router(bom.router)
app.include_router(spc.router)
app.include_router(ppap.router)
app.include_router(fmea.router)
app.include_router(basic_data.router)
app.include_router(wms.router)
app.include_router(trial.router)
app.include_router(lab.router)
app.include_router(system.router)

# 健康检查
@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


# 未知 /api/v1/* 路径兜底：返回结构化 404 JSON（SPA 路由不受影响）
@app.get("/api/v1/{full_path:path}")
async def api_not_found(full_path: str):
    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found", "code": "ROUTE_NOT_FOUND"},
    )

# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "code": "500-0000",
            "message": "内部服务异常",
            "request_id": str(uuid.uuid4())[:8],
        },
    )

# 请求 ID 中间件
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:12]
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response
