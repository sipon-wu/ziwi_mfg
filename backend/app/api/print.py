"""单据打印与留痕回查（M00-平台治理）。

## 为什么打印要走服务端

纸质单据在制造业是**审核证据**（ISO 9001 7.5 成文信息）。浏览器 `window.print()`
出的纸有三个致命问题：

1. **时间与操作人由浏览器决定** —— 改系统时间、改 DOM，纸上就是另一个时间、
   另一个人。
2. **内容不可复现** —— 打印后记录被改，"这张纸当时到底写了什么"无从回答。
3. **分不清原件与复印件** —— 同一张单打十次，十张纸一模一样。

所以这里走服务端出 PDF：留痕码、副本号、版本号、打印时间、打印人全部由服务端
写死进 PDF 字节，前端改不了；快照与哈希入库，任何时候都能回查。

## 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/print/{doc_type}/{doc_id}` | 出 PDF（同时落留痕），返回 PDF 字节 |
| GET | `/print/artifacts` | 留痕列表（**不返回 PDF 字节**） |
| GET | `/print/artifacts/{id}/pdf` | 补打/重下**历史那份** PDF |
| GET | `/print/verify/{verify_code}` | 扫码回查：这张纸真不真、还有效吗 |

⚠️ 补打与重打的区别是这里唯一容易搞错的语义：
**重打**（再调一次 POST）会生成新副本号、内容用**当前**数据；
**补打**（GET 历史 PDF）拿到的是**当时那张纸的字节**。审核补材料必须用后者，
否则补出来的纸内容与当初交出去的不一致。
"""

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.services.print import REGISTRY
from app.services.print_service import (
    PAPERS,
    PrintDocNotFound,
    PrintDocTypeUnknown,
    PrintService,
)

router = APIRouter(prefix="/api/v1/print", tags=["M00-打印留痕"])


def _ascii_name(name: str) -> str:
    """Content-Disposition 的 ASCII 兜底名。

    单号里可能带中文（如 "客诉-2026-007"），直接塞 header 会触发
    `UnicodeEncodeError`/乱码。规范做法是 ASCII fallback + `filename*=UTF-8''`。
    """
    safe = "".join(ch if ch.isascii() and ch.isprintable() and ch not in '"\\' else "_"
                   for ch in name)
    return safe or "document.pdf"


def _content_disposition(name: str) -> str:
    return f"inline; filename=\"{_ascii_name(name)}\"; filename*=UTF-8''{quote(name)}"


def _svc(current_user: dict, db: AsyncSession) -> PrintService:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail={
            "code": "NO_TENANT", "message": "当前登录用户未绑定租户，无法打印"})
    return PrintService(db, tenant_id)


def _guess_source(request: Request) -> tuple[str, str]:
    """粗判终端类型，只作辅助线索（真值以留痕码回查为准）。

    区分 pda 的意义：车间手持终端上打出来的纸与办公室打出来的纸，
    排障时看到「这张是 PDA 打的」能立刻排除打印机驱动这类猜测。
    """
    ua = (request.headers.get("user-agent") or "").lower()
    if any(k in ua for k in ("pda", "handheld", "zebra", "urovo", "i6310", "chainway")):
        return "pda", ua[:200]
    if request.headers.get("x-client") == "kiosk":
        return "kiosk", ua[:200]
    return "web", ua[:200]


@router.post("/{doc_type}/{doc_id}")
async def render_print(
    doc_type: str,
    doc_id: str,
    request: Request,
    paper: str = Query("a4", description="纸型：a4 归档件 / label80 热敏贴标"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """出 PDF 并落留痕。

    返回 `application/pdf` 字节流，留痕元信息放在响应头 `X-Print-*` 上，
    前端不必再多调一次接口就能拿到留痕码/版本/副本号。
    """
    if doc_type not in REGISTRY:
        raise HTTPException(status_code=400, detail={
            "code": "PRINT_DOC_TYPE_UNKNOWN",
            "message": f"不支持打印的单据类型：{doc_type}（已支持：{'/'.join(REGISTRY)}）",
        })

    if paper not in PAPERS:
        # 纸型走参数而不是新路由：新增路径会再造一个无人拥有的权限码
        # （EXECUTE_SUFFIXES 同类问题已经踩过 6 次）。
        raise HTTPException(status_code=400, detail={
            "code": "PRINT_BAD_PAPER",
            "message": f"不支持的纸型：{paper}（可选：{'/'.join(PAPERS)}）",
        })

    # ★ 单号合法性在这里单独判，不要靠下面的兜底 except：
    #   实测踩过 —— 构建器把 Decimal 塞进快照、json.dumps 抛 TypeError，
    #   被兜底 except 翻译成「单据标识不合法：3（Object of type Decimal is
    #   not JSON serializable）」。单号明明是对的，文案却指着单号，
    #   排查方向被带偏半天。入参校验与渲染失败必须分开报。
    try:
        int(doc_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail={
            "code": "PRINT_BAD_DOC_ID", "message": f"单据标识不合法：{doc_id}（应为数字主键）"})

    svc = _svc(current_user, db)
    source, hint = _guess_source(request)
    actor_name = current_user.get("real_name") or current_user.get("username") or ""

    try:
        info = await svc.render_and_store(
            doc_type, doc_id, paper=paper,
            actor_id=current_user.get("id"),
            actor_name=actor_name,
            print_source=source,
            client_hint=hint,
        )
    except PrintDocTypeUnknown as e:
        raise HTTPException(status_code=400, detail={"code": "PRINT_DOC_TYPE_UNKNOWN", "message": str(e)})
    except PrintDocNotFound as e:
        raise HTTPException(status_code=404, detail={"code": "PRINT_DOC_NOT_FOUND", "message": str(e)})
    except (ValueError, TypeError) as e:
        # 走到这里说明单号已经校验过（上面 int(doc_id) 已过），
        # 所以问题出在构建器 / 渲染阶段，不该再说是"单号不合法"。
        raise HTTPException(status_code=500, detail={
            "code": "PRINT_RENDER_FAILED",
            "message": f"打印渲染失败：{type(e).__name__}: {e}"})

    pdf, _name, _pages = await svc.get_pdf(info["id"])
    # 文件名带纸型：同一单打出的 A4 与贴标落进同一个下载目录时不会互相覆盖，
    # 后面靠文件名也能认出哪张是归档件。
    suffix = "-label" if paper != "a4" else ""
    filename = f"{info['doc_no']}-V{info['doc_revision']}C{info['copy_no']}{suffix}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # inline：浏览器直接开预览，用户再按打印。attachment 会变成下载
            # 走「下载目录→打开→打印」三步，车间现场多两步就是多一倍卡壳。
            "Content-Disposition": _content_disposition(filename),
            "X-Print-Artifact-Id": str(info["id"]),
            "X-Print-Verify-Code": info["verify_code"],
            "X-Print-Doc-No": info["doc_no"],
            "X-Print-Revision": str(info["doc_revision"]),
            "X-Print-Copy-No": str(info["copy_no"]),
            "X-Print-Page-Count": str(info["page_count"]),
            "X-Print-Paper": info["paper"],
            "X-Print-Template": f"{info['template_code']} v{info['template_version']}",
            "X-Print-At": info["printed_at"],
        },
    )


@router.get("/artifacts")
async def list_artifacts(
    doc_type: Optional[str] = Query(None),
    doc_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="valid / superseded / voided"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    request: Request = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """打印留痕列表（当前租户内）。"""
    svc = _svc(current_user, db)
    data = await svc.list_artifacts(
        doc_type=doc_type, doc_id=doc_id, status=status, page=page, page_size=page_size,
    )
    return {"code": 0, "message": "success", "data": data}


@router.get("/artifacts/{artifact_id}/pdf")
async def download_artifact_pdf(
    artifact_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取**当时那份** PDF（补打用）。

    与 `POST /print/...` 的区别见模块 docstring：这里是历史字节，不是重新生成。
    """
    svc = _svc(current_user, db)
    try:
        pdf, name, _pages = await svc.get_pdf(artifact_id)
    except PrintDocNotFound as e:
        raise HTTPException(status_code=404, detail={"code": "PRINT_ARTIFACT_NOT_FOUND", "message": str(e)})
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(name)},
    )


@router.get("/verify/{verify_code}")
async def verify_print(
    verify_code: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """扫码回查。

    ⚠️ 刻意的设计取舍：**要求登录**。开放匿名回查会让任何人拿一个码就能探出
    「某个租户有没有这张单、单号是什么」，等于送一个跨租户枚举接口。代价是
    外来审核员需要账号——那本来就是内部审核场景。
    """
    svc = _svc(current_user, db)
    data = await svc.verify(verify_code)
    return {"code": 0, "message": "success" if data.get("found") else "not_found", "data": data}
