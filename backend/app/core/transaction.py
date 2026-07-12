"""过账事务边界（方案 B —— 确认即过账）。

提供显式 + 防御性的事务收口，防止未来有人在过账中途误加 ``commit()`` 破坏原子性。

依赖 ``app.core.database.get_db`` 的 per-request 单 session 语义：
同一请求内 ``wms.py`` 里多个 ``get_tenant_repo(X)`` 拿到的 ``repo._session`` 是同一个对象，
因此 ``store_item`` / ``issue_item`` / ``receive_item`` 内的 ``stock_*`` 与 ``tx.create``
天然在 **同一事务** 里。任一步抛异常，由 ``get_db`` 整体回滚，库存与流水要么都成、要么都回退。

设计原则：过账函数（receive/store/issue ...）内部 **禁止调用 session.commit()**；
所有写入在 ``posting_scope`` 内完成，提交权唯一归属于 ``get_db``。
"""
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


class PostingError(Exception):
    """过账业务异常。

    携带错误码（与现有 ``400-0000`` 风格一致）与对应 HTTP 状态码，
    由 API 层统一映射为 ``HTTPException(4xx, detail={"code": ..., "message": ...})``。
    """

    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


@asynccontextmanager
async def posting_scope(session: AsyncSession):
    """过账事务边界（依赖 request-scoped 单事务）。

    块内所有 repo 操作共享同一 session；任一步异常向上抛，由 ``get_db`` 统一 rollback，
    保证 inventory 更新 + transaction 写入原子完成。

    此处只 ``flush`` 不 ``commit``（避免提前提交破坏请求级原子性）。
    """
    try:
        yield
        await session.flush()
    except Exception:
        # 任一步失败 → 整请求回滚（与 get_db 的 rollback 双保险）
        await session.rollback()
        raise
