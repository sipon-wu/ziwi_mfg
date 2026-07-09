# FastAPI 应用入口
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uuid

from app.core.config import get_settings
from app.core.database import init_db, ensure_engine
from app.core.scheduler import init_scheduler, start_scheduler, shutdown_scheduler
from app.api import auth, tenants, users, roles, excel_import, production, dictionary, messages, approvals, organization, tpm, quality, andon, energy, sync, data_collection, bom, spc, ppap, fmea, basic_data, wms, trial, lab

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

    yield

    # 关闭时
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

# 健康检查
@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


# 系统配置概览
@app.get("/api/v1/system/config")
async def system_config():
    """返回系统配置概览（版本、模块列表、状态）"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "version": "1.0.0",
            "app_name": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "debug": settings.APP_DEBUG,
            "modules": [
                {"code": "M01", "name": "生产管理", "status": "active", "routes": ["/api/v1/production"]},
                {"code": "M02", "name": "设备管理(TPM)", "status": "active", "routes": ["/api/v1/tpm"]},
                {"code": "M03", "name": "品质管理", "status": "active", "routes": ["/api/v1/quality"]},
                {"code": "M04", "name": "安灯管理", "status": "active", "routes": ["/api/v1/andon"]},
                {"code": "M05", "name": "异常管理", "status": "active", "routes": ["/api/v1/quality"]},
                {"code": "M07", "name": "组织架构", "status": "active", "routes": ["/api/v1/organization"]},
                {"code": "M08", "name": "消息中心", "status": "active", "routes": ["/api/v1/messages"]},
                {"code": "M09", "name": "审批管理", "status": "active", "routes": ["/api/v1/approvals"]},
                {"code": "M10", "name": "基础数据", "status": "active", "routes": ["/api/v1/dictionary"]},
                {"code": "M11", "name": "能碳管理", "status": "active", "routes": ["/api/v1/energy"]},
                {"code": "M12", "name": "数据采集", "status": "active", "routes": ["/api/v1/collect"]},
                {"code": "M20", "name": "仓储管理(WMS)", "status": "active", "routes": ["/api/v1/wms"]},
                {"code": "M16", "name": "试产管理(NPI)", "status": "active", "routes": ["/api/v1/trials"]},
            ],
        },
    }

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
