from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Text, JSON, Index, func
from app.core.database import Base

# SQLite 只有 `INTEGER PRIMARY KEY` 才是 rowid 别名（可自增）；
# `BIGINT PRIMARY KEY` 不是，插入必须显式给 id。故 sqlite 方言下降级为 Integer。
# PG 仍为 BIGINT，与生产一致。
PK_BIGINT = BigInteger().with_variant(Integer, "sqlite")


class EntityStatusLog(Base):
    """通用状态变更流水（平台层 M02）。

    设计出处：docs/通用状态流水设计-2026-10-29.md

    为什么是一张通用表而不是每张业务表配一张 `*_status_logs`
    -------------------------------------------------------
    评审（docs/精益与架构方案全面评审-2026-10-29.md P0-2）发现多数模块缺状态流水。
    逐表配 log 的模式无法支撑两类**全局**需求：
      1. 决策流看板：跨 biz_type 统一计算 SLA（需 GROUP BY 业务类型）
      2. 精益体检：跨模块计算状态停留时长（需一套算法覆盖全部模块）
    通用表以 `entity_type` + `entity_id` 承载，一张表同时满足两者，并使新增模块零成本接入。

    一次投入同时支撑（原为四套独立需求）：
      - OEE 可用性：entity_type=equipment 的状态轨迹
      - 决策流 SLA：entity_type=approval_node / approval_instance 的停留时长
      - NCR 流动与闭环：entity_type=ncr
      - 外部回执留痕：source=integration（审核外接 QA）

    ★ 写入约定
      - **append-only**：本表只允许 INSERT，**不提供 UPDATE / DELETE**（Service 层不暴露）
      - 必须经 `StatusLogService.record()` 写入，**禁止各模块手写 INSERT**，否则口径必散
      - `occurred_at` **不允许事后补录/修改**（用户 2026-10-29 决策）；
        它用于记录**事件真实发生时间**——当来源是外部系统回执（source=integration）时，
        可传入外部系统的时间戳；此时 `created_at` 才是本系统的写入时刻，两者分离以便追溯
    """
    __tablename__ = "entity_status_logs"
    __table_args__ = (
        # 主路径 1：查单个对象的流转轨迹
        Index("idx_esl_entity", "tenant_id", "entity_type", "entity_id", "occurred_at"),
        # 主路径 2：体检/看板聚合（停留时长、积压、超时）
        Index("idx_esl_agg", "tenant_id", "entity_type", "to_status", "occurred_at"),
    )

    id = Column(PK_BIGINT, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    entity_type = Column(
        String(50), nullable=False,
        comment="ncr/work_order/approval_instance/approval_node/equipment/inspection_order/trial_order/scar ...",
    )
    entity_id = Column(BigInteger, nullable=False)
    entity_no = Column(String(100), comment="单号快照，便于人工排查")
    from_status = Column(String(50))
    to_status = Column(String(50), nullable=False)
    action = Column(String(50), comment="create/submit/approve/reject/dispose/close/escalate ...")
    actor_id = Column(BigInteger)
    actor_name = Column(String(200), comment="操作人姓名快照（人员可能离职/改名）")
    source = Column(
        String(20), nullable=False, server_default="system",
        comment="system/manual/integration（自动/人工/外部系统回执）",
    )
    occurred_at = Column(
        DateTime(timezone=True), nullable=False,
        comment="事件真实发生时间；禁止事后补录。外部回执场景可传外部系统时间戳",
    )
    reason = Column(Text)
    extra = Column(JSON, comment="附加上下文，如超时天数、升级层级")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="本系统写入时刻")
