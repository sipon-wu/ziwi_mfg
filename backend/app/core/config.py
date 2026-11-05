# Pydantic Settings 读取环境变量
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, model_validator
from typing import Optional
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "ziwi"
    APP_ENV: str = "development"
    # debug 默认按环境推断：仅 development/dev/local 开启；
    # 可被显式设置 APP_DEBUG=true/false 覆盖（staging / production 默认关闭）。
    APP_DEBUG: Optional[bool] = None
    APP_SECRET_KEY: str = "change_me_in_production_32_chars_min"
    APP_CORS_ORIGINS: str = "*"
    # 业务时区偏移（小时）。容器跑 UTC、业务在 CST，用 ``date.today()`` 取"今天"
    # 会在 UTC 16:00–24:00 这 8 小时里比业务日**早一天**（详见 core/business_time.py）。
    # 需要别的时区时只改这个值，不要改业务代码。
    BUSINESS_UTC_OFFSET_HOURS: int = 8

    # 数据库 - 默认使用 SQLite（aiosqlite），.env 中设 DB_DRIVER=postgresql 可切换
    DB_DRIVER: str = "sqlite"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "ziwi"
    DB_USER: str = "ziwi"
    DB_PASSWORD: str = "ziwi_dev_password"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO_SQL: bool = False

    @property
    def DATABASE_URL(self) -> str:
        if self.DB_DRIVER == "sqlite":
            return "sqlite+aiosqlite:///./ziwi.db"
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # ── 权限体系（S1/S2）──
    # True  = 强制模式：无权限直接 403（当前默认）。
    # False = 影子模式：只记录"本该 403 但放行"，用于排查"改了授权但不确定影响面"。
    PERMISSION_ENFORCE: bool = True
    # 灰度开关：逗号分隔的模块码（如 "M01,M03"）。非空时**只有这些模块**走强制模式，
    # 其余模块仍按影子模式放行。空 = 全量生效。
    # 用途：切全量前先灰度两三个模块，出问题把这一项一改即可回退，无需重启回滚代码。
    PERMISSION_ENFORCE_MODULES: str = ""
    # True 时启动会校验"每个 /api/v1 路由都有权限声明"，缺失则启动失败（fail-closed）。
    PERMISSION_STRICT_STARTUP: bool = False

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "ziwi_redis_password"
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── 打印留痕 ───────────────────────────────────────────────────────
    # 二维码要指向**人能看到的前端页面**，不是 API。前端是 hash 路由，
    # 因此形如 `<PUBLIC_WEB_URL>/#/print/verify/<code>`。
    # 不能从 request.base_url 推导：反向代理后端的 host 与前端域名常常不同
    # （nginx 把 /api 反代到容器，但二维码要扫到站点的前端地址）。
    # ⚠️ 部署到 staging / 生产时必须设 `PUBLIC_WEB_URL=https://mfg1.ziwi.cn`，
    # 否则二维码指向 localhost:5173，扫出来是打不开的地址（纸已印发，改不了）。
    PUBLIC_WEB_URL: str = "http://localhost:5173"

    # ── 已废弃的时区配置（只剩启动期冲突检测）───────────────────────────
    # 曾经有三个同义开关：PRINT_TZ_OFFSET_HOURS（纸面打印时间）、
    # COPILOT_TZ_OFFSET_HOURS（Copilot 的"今天/昨天/本月"）、
    # BUSINESS_UTC_OFFSET_HOURS（业务日历日）。三者都是"+8，业务当地时间"，
    # 各存一份 → 改一处漏一处就会分叉：纸面按 +9 打、拣选效期按 +8 判，
    # 而两处都不会报错。
    #
    # 现在**唯一真源是 BUSINESS_UTC_OFFSET_HOURS**，下面两个只为"不让旧部署静默失效"
    # 而保留：`:class:`Settings` 是 extra="ignore"，直接删键的话，
    # 一个把 PRINT_TZ_OFFSET_HOURS 设成 6 的现场（新疆一类）会在升级后
    # **无声地**变成 8 —— 纸面时间偏 2 小时，纸质记录的证据价值就没了。
    # 所以键留着，值只要与主开关不一致就在启动期直接抛错（见 _check_legacy_tz_keys）。
    PRINT_TZ_OFFSET_HOURS: Optional[int] = None
    COPILOT_TZ_OFFSET_HOURS: Optional[int] = None

    # 热敏标签纸实际规格。不同客户现场的标签纸与模切刀具尺寸不同，且无法提前
    # 穷举（用户原话：「标签纸好像也不好提前穷举」），所以不在代码里建规格库 ——
    # 现场量一次，改这两个环境变量即可，无需发版。
    # 单位 mm；高度只影响版面留白，内容不足时下方留白，不压缩字号。
    # 取值非法（≤0 / 非数字 / 大到不像纸）时渲染器会兜底回默认值，不抛异常 ——
    # 现场一个手误不该让整个打印接口 500。
    PRINT_LABEL_W_MM: float = 80.0
    PRINT_LABEL_H_MM: float = 60.0

    # ── cloud.ziwi.cn 统一 JWT 认证配置（RS256 非对称验签） ──

    CLOUD_JWKS_URL: str = "https://cloud.ziwi.cn/api/v1/auth/public-key"
    CLOUD_JWKS_CACHE_TTL: int = 3600          # JWKS 缓存 TTL（秒），默认 1 小时
    CLOUD_JWKS_FETCH_TIMEOUT: float = 5.0     # 拉取 JWKS 超时（秒）
    CLOUD_EXPECTED_ALGORITHM: str = "RS256"   # cloud JWT 签名算法
    CLOUD_CLOCK_SKEW_SECONDS: int = 30        # 时钟偏差容忍（秒）

    # ── 以下 JWT 配置已废弃（保留字段名避免下游报错，不再用于本地签发） ──
    # 本地签发 JWT 已移除，所有 token 验签通过 cloud JWKS 公钥完成。
    JWT_SECRET_KEY: str = "change_me_jwt_secret_32_chars_min"    # [DEPRECATED]
    JWT_ALGORITHM: str = "HS256"                                  # [DEPRECATED]
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30                     # [DEPRECATED] cloud 控制过期时间
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7                        # [DEPRECATED] cloud 控制过期时间

    # 日志
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # ── AI Copilot（E1 只读 MVP）────────────────────────────────────────
    COPILOT_ENABLED: bool = True                       # Copilot 总开关
    COPILOT_MIN_CONFIDENCE: float = 0.6                # 低于该阈值触发澄清反问（R7）
    AI_GATEWAY_URL: str = "http://localhost:8100"      # ai-gateway 服务地址（OpenAI 兼容）
    AI_CHAT_MODEL: str = "qwen-plus"                   # 话术组织模型
    AI_INTENT_MODEL: str = "qwen-turbo"                # 意图解析模型（structured output）
    AI_EMBED_MODEL: str = "text-embedding-v3"          # 向量模型
    AI_GATEWAY_ENABLED: bool = True                    # False 时直接走降级链路
    AI_GATEWAY_TIMEOUT: float = 15.0                   # 调用 ai-gateway 超时（秒）

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def _check_legacy_tz_keys(self) -> "Settings":
        """旧时区开关与主开关冲突时**启动即失败**，不要静默走默认值。

        为什么必须响亮：``extra="ignore"`` 会把未声明的环境变量直接丢掉。若删键后
        一个把 ``PRINT_TZ_OFFSET_HOURS`` 设成别的值的现场升级，纸面打印时间会从
        "+6" 悄悄变成 "+8"，而系统一切正常、接口全 200 —— 只有纸质记录上的时间
        错了。这类"看得见的纸、看不见的错"必须用启动失败拦住。
        """
        conflicts = []
        for name in ("PRINT_TZ_OFFSET_HOURS", "COPILOT_TZ_OFFSET_HOURS"):
            legacy = getattr(self, name, None)
            if legacy is not None and int(legacy) != int(self.BUSINESS_UTC_OFFSET_HOURS):
                conflicts.append(f"{name}={legacy}")
        if conflicts:
            raise ValueError(
                f"时区配置冲突：{' / '.join(conflicts)} 已废弃，"
                f"与 BUSINESS_UTC_OFFSET_HOURS={self.BUSINESS_UTC_OFFSET_HOURS} 不一致。"
                "纸面打印时间、Copilot 的「今天/昨天/本月」与业务日历日必须共用同一个偏移 —— "
                "请删掉这些旧环境变量，只保留 BUSINESS_UTC_OFFSET_HOURS。"
            )
        return self

    @property
    def IS_DEBUG(self) -> bool:
        """FastAPI 调试模式开关：默认按环境推断，仅开发环境开启。"""
        if self.APP_DEBUG is not None:
            return self.APP_DEBUG
        return self.APP_ENV in ("development", "dev", "local")

@lru_cache()
def get_settings() -> Settings:
    return Settings()
