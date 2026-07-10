# 系统级只读接口：健康检查、系统配置、许可证状态
from fastapi import APIRouter, Depends
from app.core.config import get_settings
from app.core.dependencies import get_current_user

settings = get_settings()

router = APIRouter(prefix="/api/v1/system", tags=["系统配置"])


@router.get("/health")
async def system_health():
    """API 层健康检查（无需鉴权）。"""
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


@router.get("/config")
async def system_config(current_user: dict = Depends(get_current_user)):
    """返回系统配置概览（版本、模块列表、状态）。需登录鉴权。"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "version": "1.0.0",
            "app_name": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "debug": settings.IS_DEBUG,
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


@router.get("/license")
async def system_license():
    """许可证状态查询。

    后端「许可证管理」模块尚未实现，返回「未配置」占位状态，
    前端据此展示真实状态或「许可证模块待上线」占位（禁止返回假数据）。
    """
    return {
        "code": 0,
        "message": "许可证模块待上线",
        "data": {
            "status": "not_configured",
            "message": "许可证管理模块尚未在 mfg 平台实现",
        },
    }
