"""打印子系统（服务端出 PDF + 快照留痕）。

三个文件各管一件事，不要互相渗透：

- ``renderer.py``  —— A4 归档件（platypus）。只认 ``PrintDoc``／``RenderMeta``，
  不知道数据库存在。
- ``label.py``     —— 热敏 80mm 标签（canvas 直绘）。同一份 ``PrintDoc``，
  只裁版面、不改内容。
- ``registry.py``  —— 只把数据库记录翻译成 ``PrintDoc``，只读不写。
- ``print_service.py``（上一级）—— 编排：取快照 → 算哈希 → 定版本/副本号 →
  渲染 → 存库 → 写审计。

这样分层的原因：**排版逻辑不能依赖 ORM**。一旦渲染器开始直接查库，
每加一种单据就得改渲染器，而模板版本号（``TEMPLATES`` / ``LABEL_TEMPLATES``）
也就失去意义了。

## 两种纸型的分工

| 纸型 | 渲染器 | 用途 | 特征 |
|---|---|---|---|
| ``a4`` | ``render_pdf`` | 归档件（流转卡、检验记录单） | 分页、页码 N/M、签署栏、二维码回查 |
| ``label80`` | ``render_label`` | 现场贴标 | 单页、无页码、无签署栏、纯黑白 |

**两种纸型共用同一个快照**，因此 ``content_hash`` 相同 —— 这是刻意设计：
补打时才能判断"贴在这台设备上的标签，与档案柜里那份是不是同一次打印的内容"。
"""

from app.services.print.label import (
    LabelSpec,
    default_label_spec,
    render_label,
)
from app.services.print.renderer import (
    PrintDoc,
    RenderMeta,
    Section,
    render_pdf,
)
from app.services.print.registry import (
    LABEL_TEMPLATES,
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
    "LabelSpec",
    "render_label",
    "default_label_spec",
    "REGISTRY",
    "TEMPLATES",
    "LABEL_TEMPLATES",
    "build_work_order",
    "build_inspection_order",
]
