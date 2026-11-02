"""服务端幂等键 —— 给"不能重复执行"的写操作提供去重凭证。

## 为什么需要这张表

出库过账（`POST /wms/issue-order-items/{id}/issue`）**每调一次就真扣一次库存**。
前端 `useSubmitLock` 只能挡住"同一个页面里的连点"，挡不住这些真实场景：

- 现场网络抖动 → 请求已到服务端、响应没回来 → 用户看没反应再点一次；
- 手持终端扫完码页面重载，用户重试；
- 同一个人用两个标签页/两台设备操作同一张单。

这些都会让同一笔出库扣两遍库存，而库存是**没有"撤销"直觉**的数据 ——
账面少了 100 件，事后只能靠盘点倒推。所以幂等键必须在服务端。

## 语义

`(tenant_id, request_id)` 唯一。客户端为"一次逻辑操作"生成一个 `request_id`，
重试时**沿用同一个**；服务端据此判定：

| 状态 | 行为 |
|---|---|
| 首次 | 占位 `in_progress` → 执行业务 → 标记 `done` 并存响应 |
| 已 `done` | **不重复执行**，原样返回上次的响应（客户端拿到一致结果） |
| 仍 `in_progress` | 409，让客户端知道"上一次还在处理" |
| 业务失败 | 整条请求事务回滚 → 占位行一并消失 → 允许重试 |
| 已过期 | 15 分钟后可复用同一 `request_id`（占位行被清理） |

## 为什么失败要连占位行一起扔

幂等键的目的是"**防止重复产生副作用**"，不是"防止重试"。业务失败时副作用没发生，
若把键留在 `in_progress`，用户会被自己的第一次失败锁死 15 分钟 —— 那是把
幂等做成了拒绝服务。

## 与 `posting_scope` 的关系

本表写入与业务写入共享同一个 request-scoped 事务（见 `core/transaction.py`），
所以"业务回滚则键回滚"是天然成立的，不需要额外补偿逻辑。
占位用 SAVEPOINT（`begin_nested`）隔离：唯一键冲突时只回滚占位，
不会把外层事务（含已完成的业务写入）一起弄脏。
"""
from sqlalchemy import (
    Column, DateTime, Index, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base, PK_TYPE


class IdempotencyKey(Base):
    """幂等键占位行。"""

    __tablename__ = "idempotency_keys"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    request_id = Column(
        String(64), nullable=False,
        comment="客户端生成的幂等键（同一次逻辑操作重试时必须沿用同一个）",
    )
    endpoint = Column(
        String(64), nullable=False,
        comment="业务动作标识，如 wms.issue_item。仅用于排障，不参与唯一性",
    )
    status = Column(
        String(16), nullable=False, server_default="in_progress",
        comment="in_progress | done",
    )
    response_json = Column(Text, comment="成功响应快照（重放时原样返回）")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at = Column(
        DateTime(timezone=True), nullable=False,
        comment="过期时刻。过了这个点同一 request_id 可重新使用",
    )

    __table_args__ = (
        # ★去重口径按架构文档 §R4：`(tenant_id, request_id)`，不含 endpoint。
        #   同一 request_id 跨接口复用属于客户端 bug，此时"直接命中旧结果"
        #   比"两个接口各执行一次"安全。
        UniqueConstraint("tenant_id", "request_id", name="uq_idempotency_tenant_request"),
        # 过期清理按时间扫，必须有索引，否则每次占位都要全表扫
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - 仅排障用
        return (f"<IdempotencyKey tenant={self.tenant_id} "
                f"req={self.request_id} status={self.status}>")
