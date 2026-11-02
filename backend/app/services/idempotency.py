"""服务端幂等执行器（配合 `models/idempotency.py` 的 `idempotency_keys` 表）。

## 用法

```python
result, replayed = await run_once(
    tenant_id=tenant_id,
    request_id=req.request_id,          # 可选；不传则退化为原行为
    endpoint="wms.issue_item",
    action=lambda: svc.issue_item(...),
)
```

`request_id` 为空时**完全透传**（`return await action(), False`），所以给老客户端
加这个参数是向后兼容的，不需要同步改所有调用方。

## 为什么不是"重复就报错"而是"重复就返回上次结果"

幂等要的效果是「用户按了两次，账面只动一次，但两次都拿到**同一个成功结果**」。
若第二次返回 409/400，用户会以为第一笔没成功，接着再去改数量、换单据重做 ——
把一次小问题放大成对账问题。只有"原样重放上次响应"才能让客户端行为收敛。

真正的并发撞车（上一次还在飞）才返回 409，因为此时**没有结果可重放**。

## ★ 为什么幂等键用**独立会话**，不搭业务事务的车

第一版把占位行写在请求事务里，指望"业务回滚 → 占位一起回滚"。实测不成立：
接口把业务失败转成 `HTTPException` 之后，请求事务照样提交了，占位行以
`in_progress` 落了库（实测库里有残留行）——于是用户第一次发料失败，
**15 分钟内用同一个 request_id 重试一直 409**，被自己的失败锁死。

所以现在三条写操作各自独立提交：

| 时机 | 动作 | 独立提交的意义 |
|---|---|---|
| 开始 | 插入 `in_progress` 占位 | 立刻对其他并发请求可见 → 真正的互斥；进程崩了也会随 TTL 过期 |
| 失败 | **删掉**占位 | 失败没有副作用，必须允许重试 |
| 成功 | 置 `done` + 存响应 | 后续重复请求直接重放 |

代价：业务成功但"置 done"写失败时，键会停在 `in_progress` 直到过期（15 分钟）。
这是有意的取向前提 —— 宁可少一次重放，也不能多扣一次库存。

## 时区

`DateTime(timezone=True)` 在 PG 上读出来是 tz-aware、在 SQLite 上是 naive。
两者直接和 `datetime.now(timezone.utc)` 比较会 `TypeError`（SQLite 侧）或
比错基准（naive 被当本地时间）。所以读写一律过 `_aware()`。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.transaction import PostingError
from app.models.idempotency import IdempotencyKey

#: 默认去重窗口。15 分钟足够覆盖"网络抖动后重试 / 换个标签页再点一次"，
#: 又短到不会把同一个 request_id 长期钉死（现场半天后重做同一件活是正常的）。
DEFAULT_TTL = timedelta(minutes=15)

STATUS_DONE = "done"
STATUS_IN_PROGRESS = "in_progress"

BUSY_MESSAGE = "同一请求正在处理中，请勿重复提交"


@asynccontextmanager
async def _own_session() -> AsyncIterator[AsyncSession]:
    """幂等键专用会话：独立事务，与业务事务互不影响。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """统一成 tz-aware（UTC）。

    SQLite 不保存时区，读回来是 naive；PG 读回来是 aware。不统一就会出现
    `can't compare offset-naive and offset-aware datetimes`。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _load(session: AsyncSession, tenant_id: str,
                request_id: str) -> Optional[IdempotencyKey]:
    res = await session.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.request_id == request_id,
        )
    )
    return res.scalars().first()


def _replay(row: IdempotencyKey) -> Optional[Any]:
    """已完成的占位行 → 上次的响应；未完成或没存响应则返回 None。"""
    if (row.status or "") != STATUS_DONE or not row.response_json:
        return None
    try:
        return json.loads(row.response_json)
    except (TypeError, ValueError):
        # 响应体坏了不能当成"没执行过"——那会重复过账。明确报错更安全。
        raise PostingError(
            "WMS_409_IDEMPOTENT_IN_PROGRESS",
            "该请求此前已执行，但保存的响应无法还原；请勿重复提交，"
            "请直接查看单据当前状态",
        )


async def _drop(key_id: int) -> None:
    """撤掉占位（失败路径）。尽力而为：撤不掉也只能等 TTL 过期。

    用**独立会话**是安全的：业务失败时 `posting_scope` 已经 rollback 过请求事务，
    锁已释放，这里能立刻拿到写锁。（成功路径不能这么做 —— 那时请求事务还握着
    写锁，SQLite 单写者会直接 database is locked，见 `run_once` 的说明。）
    """
    try:
        async with _own_session() as s:
            row = await s.get(IdempotencyKey, key_id)
            if row is not None:
                await s.delete(row)
                await s.commit()
    except Exception as exc:  # noqa: BLE001 - 清理失败不能掩盖真实业务错误
        print(f"[warn] 幂等占位清理失败 key_id={key_id}: {exc}")


async def _mark_done(key_id: int, result: Any) -> None:
    """独立会话版「置 done」（仅在调用方没给请求会话时兜底用）。"""
    try:
        async with _own_session() as s:
            row = await s.get(IdempotencyKey, key_id)
            if row is not None:
                row.status = STATUS_DONE
                row.response_json = json.dumps(result, ensure_ascii=False, default=str)
                await s.commit()
    except Exception as exc:  # noqa: BLE001
        # 标记失败 → 键停在 in_progress，重复请求会被 409 拦下。
        # 这比"当成没执行过再扣一次库存"安全得多，所以不重试，但必须留痕 ——
        # 第一版这里是静默 pass，结果线上表现为"重放请求 500"，极难定位。
        print(f"[warn] 幂等键置 done 失败 key_id={key_id}: {exc}")


async def run_once(
    *,
    tenant_id: str,
    request_id: Optional[str],
    endpoint: str,
    action: Callable[[], Awaitable[Any]],
    ttl: timedelta = DEFAULT_TTL,
    mark_session: Optional[AsyncSession] = None,
) -> Tuple[Any, bool]:
    """按 ``(tenant_id, request_id)`` 去重执行一次 ``action``。

    Args:
        mark_session: 成功时写 ``done`` 用的会话。**建议传调用方的请求会话** ——
            业务写入此时还没提交、还握着写锁，另开连接去写同一张库在 SQLite 上
            会直接 ``database is locked``（第一版就是这么静默失败的：键停在
            in_progress，重放请求一路 409/500）。传请求会话则"业务成功 + 标记完成"
            随同一个事务提交，语义也更对。

    Returns:
        ``(结果, 是否重放)``。重放表示本次没有真正执行业务动作。
    """
    # 没给幂等键 = 老客户端，行为完全不变
    if not request_id:
        return await action(), False

    rid = str(request_id).strip()[:64]
    if not rid:
        return await action(), False

    now = datetime.now(timezone.utc)

    # ── 1. 占位（独立事务，立刻提交 → 对其他并发请求可见） ──
    key_id: Optional[int] = None
    async with _own_session() as s:
        existing = await _load(s, tenant_id, rid)
        if existing is not None:
            exp = _aware(existing.expires_at)
            if exp is not None and exp <= now:
                # 过期占位：清掉，当作全新请求（同一 request_id 可再次使用）
                await s.delete(existing)
                await s.commit()
                existing = None

        if existing is not None:
            cached = _replay(existing)
            if cached is not None:
                return cached, True
            raise PostingError("WMS_409_IDEMPOTENT_IN_PROGRESS", BUSY_MESSAGE)

        row = IdempotencyKey(
            tenant_id=tenant_id,
            request_id=rid,
            endpoint=endpoint,
            status=STATUS_IN_PROGRESS,
            created_at=now,
            expires_at=now + ttl,
        )
        s.add(row)
        try:
            await s.flush()
            key_id = row.id
            await s.commit()
        except IntegrityError:
            # 竞态：另一并发请求刚占位成功
            await s.rollback()
            other = await _load(s, tenant_id, rid)
            if other is not None:
                cached = _replay(other)
                if cached is not None:
                    return cached, True
            raise PostingError("WMS_409_IDEMPOTENT_IN_PROGRESS", BUSY_MESSAGE)

    # ── 2. 执行业务。失败 → 明确撤掉占位，保证可以重试 ──
    assert key_id is not None
    try:
        result = await action()
    except BaseException:
        await _drop(key_id)
        raise

    # ── 3. 成功 → 置 done 并保存响应，供重复请求重放 ──
    if mark_session is not None:
        row = await mark_session.get(IdempotencyKey, key_id)
        if row is not None:
            row.status = STATUS_DONE
            row.response_json = json.dumps(result, ensure_ascii=False, default=str)
            await mark_session.flush()
    else:
        await _mark_done(key_id, result)
    return result, False
