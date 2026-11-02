"""打印留痕模型。

## 为什么需要一张独立的表

「能打印」和「可留痕」是两件事。前者只要 `window.print()`，后者要求在
**任何时刻**都能回答四个问题：

1. 这张纸对应系统里的哪条记录、哪个版本？（`doc_no` + `doc_revision`）
2. 打印那一刻记录长什么样？（`snapshot_json` + `content_hash`）
3. 谁、在什么时候、第几次打的？（`printed_by` + `created_at` + `copy_no`）
4. 这张纸现在还有效吗？（`status`：改单后旧纸 superseded，红冲后 voided）

少了任何一条，纸质件就不能作为审核证据——而这正是制造业打印单据的用途
（ISO 9001 7.5 成文信息、IATF 16949 记录保存）。

## 几个刻意的取舍

- **PDF 字节存库**（`file_bytes`）而不是存路径：留痕的核心是"记录与文件是
  一体的"。存路径会两条命：文件被清理、容器重建丢卷、备份不一致。几十到几百 KB
  的 PDF 放 bytea 换来的是原子性。
- **`content_hash` 用快照 JSON 的规范化哈希**，不是 PDF 字节的哈希：PDF 里含
  生成时间，字节哈希每次都不同，没法判断"内容是否变过"。快照哈希才回答
  "这份单据的内容改没改"。
- **`template_code` + `template_version` 必须落库**：改了打印模板，半年前的纸
  就复现不出来。模板版本不进库，留痕在第一次改模板那天就失效了。
- **`copy_no` 单调递增**：同一版本重打必须能看出来是第几份，否则一叠纸里
  分不清哪张是原件。
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base, PK_TYPE


class PrintArtifact(Base):
    """一次打印产生的留痕记录（一条纸对应一行）。"""

    __tablename__ = "print_artifacts"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")

    # ── 对应哪条记录 ──
    doc_type = Column(String(40), nullable=False, comment="单据类型，如 work_order")
    doc_id = Column(String(80), nullable=False, comment="业务主键（存字符串以容纳编号与自增ID）")
    doc_no = Column(String(80), comment="单号快照（单据被删除后仍可追溯）")
    doc_revision = Column(Integer, default=1, nullable=False, comment="单据版本：内容变化时 +1")
    copy_no = Column(Integer, default=1, nullable=False, comment="副本号：同版本第几次打印")
    doc_status = Column(String(30), comment="打印时刻单据状态快照")

    # ── 打印了什么 ──
    template_code = Column(String(60), nullable=False, comment="打印模板标识")
    template_version = Column(String(20), nullable=False, comment="打印模板版本")
    snapshot_json = Column(JSON, comment="打印时刻的完整内容快照")
    content_hash = Column(String(64), nullable=False, comment="快照规范化 JSON 的 sha256")

    # ── 谁在哪打的 ──
    printed_by = Column(BigInteger, comment="操作人ID")
    printed_by_name = Column(String(100), comment="操作人姓名快照（改名/离职后仍可追溯）")
    print_source = Column(String(40), comment="终端来源：web / pda / kiosk")
    client_hint = Column(String(200), comment="终端标识（UA 或工位标识），仅作辅助线索")

    # ── 这张纸还有效吗 ──
    status = Column(String(20), default="valid", nullable=False, comment="valid / superseded / voided")
    superseded_by = Column(BigInteger, comment="被哪条留痕取代（改单后重打）")

    # ── 文件 ──
    verify_code = Column(String(16), nullable=False, comment="二维码回查码")
    page_count = Column(Integer, default=1)
    file_bytes = Column(LargeBinary, comment="PDF 字节（与记录同生共死）")
    file_size = Column(Integer, comment="字节数，便于列表展示不拉大字段")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "verify_code", name="uq_print_verify_code"),
        Index("ix_print_doc", "tenant_id", "doc_type", "doc_id"),
        Index("ix_print_created", "tenant_id", "created_at"),
        {"comment": "打印留痕（每次打印一行，含内容快照与 PDF）"},
    )
