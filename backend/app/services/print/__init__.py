"""打印子系统（服务端出 PDF + 快照留痕）。

三个文件各管一件事，不要互相渗透：

- ``renderer.py``  —— 只认 ``PrintDoc``／``RenderMeta``，不知道数据库存在。
- ``registry.py``  —— 只把数据库记录翻译成 ``PrintDoc``，只读不写。
- ``print_service.py``（上一级）—— 编排：取快照 → 算哈希 → 定版本/副本号 →
  渲染 → 存库 → 写审计。

这样分层的原因：**排版逻辑不能依赖 ORM**。一旦渲染器开始直接查库，
每加一种单据就得改渲染器，而模板版本号（``TEMPLATES``）也就失去意义了。
"""

from app.services.print.renderer import (
    PrintDoc,
    RenderMeta,
    Section,
    render_pdf,
)
from app.services.print.registry import (
    REGISTRY,
    TEMPLATES,
    build_inspection_order,
    build_work_order,
)

__all__ = [
    "PrintDoc",
    "RenderMeta",
    "Section",
    "render_pdf",
    "REGISTRY",
    "TEMPLATES",
    "build_work_order",
    "build_inspection_order",
]
