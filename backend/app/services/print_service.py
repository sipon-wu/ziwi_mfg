"""打印留痕编排服务。

## 它解决的问题

「打印」在制造现场不是「把屏幕像素搬到纸上」，而是**产生一份可被审核的证据**。
一份能当证据的纸必须能回答：这是哪条记录的第几版、打印那一刻内容长什么样、
谁第几次打的、现在还有效吗。本服务负责把这四个答案固化下来。

## 一次打印的完整链路

1. `REGISTRY[doc_type]` 把记录读成 `PrintDoc`（只读）
2. `PrintDoc.to_snapshot()` → 规范化 JSON → sha256 = `content_hash`
3. 与**该单据最新一条留痕**比对 `content_hash`，决定 `doc_revision` 与 `copy_no`
4. 渲染 PDF（含留痕码、副本号、模板版本、二维码）
5. 落 `print_artifacts`（PDF 字节与记录同生共死）
6. 版本变化时把旧留痕标 `superseded`
7. 写 `audit_logs`

## 三个刻意的判断

- **打印不是幂等操作**。同一单据打三次就是三份纸，各有各的副本号，
  所以**不加** `request_id` 幂等键——加了反而会让「重打一份」变成静默空操作。
- **版本号由内容哈希驱动，不由调用方指定**。若允许前端传 `revision`，
  前端就能造出「同一版本不同内容」的纸，留痕当场失效。
- **旧纸标 superseded 而不是删**。审核要看的是「当时给我看的是什么」，
  删掉旧记录等于篡改历史。作废（红冲）走 `voided`，与改单的 `superseded` 分开。
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update

from app.core.config import get_settings
from app.models.print import PrintArtifact
from app.services.audit_service import AuditAction, AuditService
from app.services.print import (
    LABEL_TEMPLATES,
    REGISTRY,
    TEMPLATES,
    RenderMeta,
    render_label,
    render_pdf,
)

logger = logging.getLogger(__name__)

# 二维码回查码字符集：去掉 I / O / 0 / 1 —— 纸上打字复述时最容易混的四个
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


class PrintDocNotFound(LookupError):
    """单据不存在（或不属于当前租户）。"""


class PrintDocTypeUnknown(ValueError):
    """未注册的单据类型。"""


# 纸型常量。刻意用字符串而不是枚举：这个值会原样落进 `print_artifacts.paper_kind`
# 并从 API 透出，字符串最不容易在序列化层走样。
PAPER_A4 = "a4"
PAPER_LABEL = "label80"
PAPERS = (PAPER_A4, PAPER_LABEL)


def _now_local() -> datetime:
    """车间当地时间（容器默认 UTC，纸面时间不能用 UTC）。"""
    offset = get_settings().PRINT_TZ_OFFSET_HOURS
    return datetime.now(timezone(timedelta(hours=offset)))


def _canonical_hash(snapshot: dict) -> str:
    """快照的规范化哈希。

    `sort_keys=True`：字段顺序变化不应算「内容变了」。若哪天有人重排了
    `PrintDoc` 的字段，用自然顺序会让全部历史纸一夜之间变成 superseded ——
    那是纯噪音。
    """
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_url(code: str) -> str:
    return f"{get_settings().PUBLIC_WEB_URL.rstrip('/')}/#/print/verify/{code}"


def decide_version(
    latest_hash: Optional[str],
    latest_revision: Optional[int],
    latest_copy_no: Optional[int],
    new_hash: str,
) -> tuple[int, int]:
    """根据「最新一条留痕」决定本次的 (版本号, 副本号)。

    抽成纯函数是因为这段是留痕语义的核心，也是最容易写错的地方：
    - 内容没变 → 同一版本，副本号 +1（重打）
    - 内容变了 → 版本号 +1，副本号回到 1（改单后重新出一版）
    - 从来没打过 → 第 1 版，第 1 份

    Args:
        latest_hash: 最新留痕的 content_hash；None 表示该单据从未打印过
        latest_revision: 最新留痕的版本号
        latest_copy_no: 最新留痕的副本号
        new_hash: 本次快照的 content_hash
    """
    if latest_hash is None:
        return 1, 1
    revision = int(latest_revision or 1)
    copy_no = int(latest_copy_no or 1)
    if latest_hash == new_hash:
        return revision, copy_no + 1
    return revision + 1, 1


class PrintService:
    """打印留痕编排。会话由调用方（API 依赖）注入，事务边界也在调用方。"""

    def __init__(self, session, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    # ── 内部 ──────────────────────────────────────────────

    async def _latest(self, doc_type: str, doc_id: str) -> Optional[PrintArtifact]:
        return (
            await self._session.execute(
                select(PrintArtifact)
                .where(
                    PrintArtifact.tenant_id == self._tenant_id,
                    PrintArtifact.doc_type == doc_type,
                    PrintArtifact.doc_id == doc_id,
                )
                .order_by(PrintArtifact.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _call_builder(self, builder, doc_type: str, doc_id: str):
        """跑 builder，把「单据不存在」统一翻译成 404 语义。

        builder 是逐单类型写的，它们各自 `raise LookupError("工单不存在…")`。
        不翻译的话 API 层只能给 500 —— 「传了别人租户的单号」会被当成服务端故障
        计入错误率，掩盖真实缺陷。
        """
        try:
            return await builder(self._session, self._tenant_id, doc_id)
        except LookupError as e:
            raise PrintDocNotFound(str(e)) from e

    async def _new_verify_code(self) -> str:
        """生成不与本租户已有记录重复的回查码。

        `uq_print_verify_code` 是 (tenant_id, verify_code) 唯一约束，冲突会让整个
        事务回滚 —— 所以先查后写，把冲突概率从「不可能」压到「不存在」。
        唯一约束仍然保留作为最后一道闸（并发下先查后写不是原子的）。
        """
        for _ in range(8):
            raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
            code = f"{raw[:4]}-{raw[4:]}"
            exists = (
                await self._session.execute(
                    select(PrintArtifact.id).where(
                        PrintArtifact.tenant_id == self._tenant_id,
                        PrintArtifact.verify_code == code,
                    )
                )
            ).first()
            if exists is None:
                return code
        raise RuntimeError("留痕码生成失败：连续 8 次撞码，检查 verify_code 长度或字符集")

    async def _tenant_name(self) -> str:
        from sqlalchemy import text

        row = (
            await self._session.execute(
                text("SELECT name FROM tenants WHERE tenant_id = :tid"),
                {"tid": self._tenant_id},
            )
        ).first()
        return (row[0] if row else "") or ""

    # ── 对外 ──────────────────────────────────────────────

    async def render_and_store(
        self,
        doc_type: str,
        doc_id: str,
        *,
        paper: str = PAPER_A4,
        actor_id: Optional[int] = None,
        actor_name: str = "",
        print_source: str = "web",
        client_hint: str = "",
    ) -> dict:
        """出一份 PDF 并落留痕。返回不含 PDF 字节的元信息字典。

        Args:
            paper: 纸型。``a4`` 出归档件（分页、页码、签署栏），``label80``
                出热敏贴标（单页、纯黑白、无签署栏）。**两种纸型共用同一份快照**，
                所以同一单据的 A4 版与标签版 `content_hash` 相同 —— 补打时才能
                证明"贴标与归档件是同一次打印的内容"。
        """
        if paper not in PAPERS:
            raise ValueError(f"不支持的纸型：{paper}（可选：{'/'.join(PAPERS)}）")

        builder = REGISTRY.get(doc_type)
        if builder is None:
            raise PrintDocTypeUnknown(
                f"不支持打印的单据类型：{doc_type}（已支持：{'/'.join(REGISTRY)}）"
            )

        pdoc = await self._call_builder(builder, doc_type, doc_id)
        snapshot = pdoc.to_snapshot()
        content_hash = _canonical_hash(snapshot)

        latest = await self._latest(doc_type, doc_id)
        revision, copy_no = decide_version(
            None if latest is None else latest.content_hash,
            None if latest is None else latest.doc_revision,
            None if latest is None else latest.copy_no,
            content_hash,
        )

        # 模板码按纸型分表取：改标签版面只 +1 标签的版本，不动 A4 归档件的解释链
        template_map = LABEL_TEMPLATES if paper == PAPER_LABEL else TEMPLATES
        if doc_type not in template_map:
            raise PrintDocTypeUnknown(
                f"单据 {doc_type} 没有登记 {paper} 模板（LABEL_TEMPLATES / TEMPLATES 需同步补齐）"
            )
        template_code, template_version = template_map[doc_type]
        verify_code = await self._new_verify_code()
        printed_at = _now_local()

        meta = RenderMeta(
            verify_code=verify_code,
            verify_url=_verify_url(verify_code),
            printed_at=printed_at.strftime("%Y-%m-%d %H:%M"),
            printed_by_name=actor_name or "未知",
            copy_no=copy_no,
            doc_revision=revision,
            template_code=template_code,
            template_version=template_version,
            tenant_name=await self._tenant_name(),
        )

        if paper == PAPER_LABEL:
            # 标签恒为单页：不数页，也不做分页 —— 热敏卷筒打多页会连成一张长纸，
            # 现场没法按单张撕下来贴。page_count 写死 1 才对得上实物。
            pdf_bytes = render_label(pdoc, meta)
            page_count = 1
        else:
            pdf_bytes, page_count = render_pdf(pdoc, meta)

        artifact = PrintArtifact(
            tenant_id=self._tenant_id,          # ★ INSERT 的 tenant_id 由应用层显式写
            doc_type=doc_type,
            doc_id=str(doc_id),
            doc_no=pdoc.doc_no,
            doc_revision=revision,
            copy_no=copy_no,
            doc_status=(pdoc.doc_status or "")[:30] or None,
            template_code=template_code,
            template_version=template_version,
            paper_kind=paper,
            snapshot_json=snapshot,
            content_hash=content_hash,
            printed_by=actor_id,
            printed_by_name=actor_name or None,
            print_source=print_source[:40] or None,
            client_hint=(client_hint or "")[:200] or None,
            status="valid",
            verify_code=verify_code,
            page_count=page_count,
            file_bytes=pdf_bytes,
            file_size=len(pdf_bytes),
            created_at=printed_at,
        )
        self._session.add(artifact)
        await self._session.flush()   # 取 id（asyncpg 没有 lastrowid，flush 走 RETURNING）

        # 版本升级：旧纸全部失效。作废（voided）的不动 —— 那已经不是「过期」而是「撤销」。
        if latest is not None and int(latest.doc_revision or 1) < revision:
            await self._session.execute(
                update(PrintArtifact)
                .where(
                    PrintArtifact.tenant_id == self._tenant_id,
                    PrintArtifact.doc_type == doc_type,
                    PrintArtifact.doc_id == str(doc_id),
                    PrintArtifact.id != artifact.id,
                    PrintArtifact.status == "valid",
                )
                .values(status="superseded", superseded_by=artifact.id)
            )

        await AuditService(self._session).log(
            AuditAction.PRINT_RENDER,
            tenant_id=self._tenant_id,
            actor_id=actor_id,
            actor_name=actor_name,
            object_type="print_artifact",
            object_id=artifact.id,
            after={
                "doc_type": doc_type,
                "doc_id": str(doc_id),
                "doc_no": pdoc.doc_no,
                "doc_revision": revision,
                "copy_no": copy_no,
                "verify_code": verify_code,
                "template": f"{template_code} v{template_version}",
                "page_count": page_count,
                "file_size": len(pdf_bytes),
            },
            message=f"打印 {pdoc.title} {pdoc.doc_no} 第 {revision} 版 副本 {copy_no}",
        )

        return {
            "id": artifact.id,
            "doc_type": doc_type,
            "doc_id": str(doc_id),
            "doc_no": pdoc.doc_no,
            "doc_revision": revision,
            "copy_no": copy_no,
            "verify_code": verify_code,
            "verify_url": _verify_url(verify_code),
            "template_code": template_code,
            "template_version": template_version,
            "paper": paper,
            "page_count": page_count,
            "file_size": len(pdf_bytes),
            "printed_at": printed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "printed_by_name": actor_name,
        }

    async def list_artifacts(
        self,
        *,
        doc_type: Optional[str] = None,
        doc_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """留痕列表。**不返回 PDF 字节**（列表页拉几十 MB 的 bytea 会拖死接口）。"""
        from sqlalchemy import func

        conds = [PrintArtifact.tenant_id == self._tenant_id]
        if doc_type:
            conds.append(PrintArtifact.doc_type == doc_type)
        if doc_id:
            conds.append(PrintArtifact.doc_id == str(doc_id))
        if status:
            conds.append(PrintArtifact.status == status)

        total = (
            await self._session.execute(
                select(func.count()).select_from(PrintArtifact).where(*conds)
            )
        ).scalar() or 0

        rows = (
            await self._session.execute(
                select(
                    PrintArtifact.id,
                    PrintArtifact.doc_type,
                    PrintArtifact.doc_id,
                    PrintArtifact.doc_no,
                    PrintArtifact.doc_revision,
                    PrintArtifact.copy_no,
                    PrintArtifact.doc_status,
                    PrintArtifact.template_code,
                    PrintArtifact.template_version,
                    PrintArtifact.paper_kind,
                    PrintArtifact.content_hash,
                    PrintArtifact.printed_by_name,
                    PrintArtifact.print_source,
                    PrintArtifact.status,
                    PrintArtifact.superseded_by,
                    PrintArtifact.verify_code,
                    PrintArtifact.page_count,
                    PrintArtifact.file_size,
                    PrintArtifact.created_at,
                )
                .where(*conds)
                .order_by(PrintArtifact.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_pdf(self, artifact_id: int) -> tuple[bytes, str, int]:
        """取 PDF 字节（重下/补打用）。返回 (bytes, 文件名, 页数)。"""
        art = (
            await self._session.execute(
                select(PrintArtifact).where(
                    PrintArtifact.id == artifact_id,
                    PrintArtifact.tenant_id == self._tenant_id,
                )
            )
        ).scalar_one_or_none()
        if art is None or not art.file_bytes:
            raise PrintDocNotFound("留痕记录不存在，或该记录没有留存 PDF")
        name = f"{art.doc_no or art.doc_type}-V{art.doc_revision}C{art.copy_no}.pdf"
        return bytes(art.file_bytes), name, int(art.page_count or 1)

    async def verify(self, verify_code: str) -> dict:
        """按留痕码回查（扫码核验）。

        刻意**只返回结论 + 摘要**，不返回 PDF、不返回快照全文：这张纸可能
        被外人捡到，扫码者只需知道「真/假、是否还有效、是谁的单」。
        """
        art = (
            await self._session.execute(
                select(PrintArtifact).where(
                    PrintArtifact.tenant_id == self._tenant_id,
                    PrintArtifact.verify_code == verify_code.strip().upper(),
                )
            )
        ).scalar_one_or_none()
        if art is None:
            return {"found": False, "verify_code": verify_code}

        snapshot = art.snapshot_json or {}
        return {
            "found": True,
            "verify_code": art.verify_code,
            "doc_type": art.doc_type,
            "doc_no": art.doc_no,
            "title": snapshot.get("title", ""),
            "doc_status": art.doc_status,
            "doc_revision": art.doc_revision,
            "copy_no": art.copy_no,
            "template": f"{art.template_code} v{art.template_version}",
            "content_hash": art.content_hash,
            # 纸型：扫一张贴标和扫一张归档件，看到的结论应当能区分开，
            # 否则现场没法判断"手里这张是不是被人从归档件上剪下来贴的"
            "paper": art.paper_kind or PAPER_A4,
            "printed_by_name": art.printed_by_name,
            "printed_at": art.created_at.strftime("%Y-%m-%d %H:%M:%S") if art.created_at else None,
            "page_count": art.page_count,
            # 这张纸现在还有效吗 —— 扫码核验最核心的一行
            "valid": art.status == "valid",
            "status": art.status,
            "superseded_by": art.superseded_by,
        }
