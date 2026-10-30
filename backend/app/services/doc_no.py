"""单据单号的唯一性守卫。

为什么需要它
------------
单号唯一性在数据库层由 ``(tenant_id, xxx_no)`` 唯一索引保证
（见 ``migrations/20261031_unique_doc_no.py``）。但唯一索引只会让
INSERT 抛 ``IntegrityError`` —— 到用户面前就是 500「服务器内部错误」，
现场只知道"提交失败"，不知道"单号重了"。

所以这层做两件事：

1. **入库前预检**：``assert_doc_no_available`` 先查一次，命中就抛 400
   并把人话写进 message（"入库单号 RC-001 已存在"）。绝大多数重复是
   用户手动填号或前端连点，预检足够覆盖。
2. **兜住竞态**：``guard_duplicate`` 把并发下才出现的 ``IntegrityError``
   翻译成同一个 400。预检与 INSERT 之间有窗口，这层不能省。

刻意不做的事
------------
- 不自动改号、不自动重试：单号带业务含义（谁开的、哪天开的），
  系统擅自改号比报错更难排查。
- 不吞其它 ``IntegrityError``：只有唯一键冲突才翻译成 400，
  外键/NOT NULL 冲突仍然抛出去暴露真实的代码缺陷。
"""
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

DUP_CODE = "400-0100"


def _dup_error(label: str, value: Optional[str]) -> HTTPException:
    if not value:
        # 自动编号（工单/试产/检验）走到这里说明是并发撞号，让用户重试即可
        return HTTPException(400, detail={
            "code": DUP_CODE,
            "message": f"{label}生成冲突（同一时刻有并发提交），请重试一次",
            "field": "doc_no",
        })
    return HTTPException(400, detail={
        "code": DUP_CODE,
        "message": f"{label} {value} 已存在，请换一个单号",
        "field": "doc_no",
    })


async def assert_doc_no_available(
    repo, table: str, column: str, value: Optional[str], label: str = "单号"
) -> None:
    """预检单号是否已被占用（同租户内）。``value`` 为空时直接放行。"""
    if not value:
        return
    row = await repo.query_one(
        f"SELECT id FROM {table} WHERE {column} = :v LIMIT 1", {"v": value}
    )
    if row:
        raise _dup_error(label, value)


async def guard_duplicate(coro, label: str, value: Optional[str] = None) -> Any:
    """等待写入协程，把唯一键冲突翻译成 400。其它异常原样抛出。"""
    try:
        return await coro
    except IntegrityError as exc:
        text = str(getattr(exc, "orig", exc)).lower()
        # 只处理唯一约束；FK / NOT NULL 冲突必须暴露成真实错误
        if "unique" in text or "duplicate" in text:
            raise _dup_error(label, value) from exc
        raise
