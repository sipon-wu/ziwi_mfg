from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, Text, DateTime, Date
from sqlalchemy.sql import func
from app.core.database import Base


class FmeaDocument(Base):
    """FMEA 文档"""
    __tablename__ = "fmea_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    doc_no = Column(String(100), nullable=False, comment="文档编号")
    fmea_type = Column(String(20), nullable=False, comment="DFMEA / PFMEA")
    title = Column(String(300), nullable=False, comment="文档标题")
    product_id = Column(BigInteger, comment="关联产品（DFMEA）")
    process_id = Column(BigInteger, comment="关联工序（PFMEA）")
    project_id = Column(BigInteger, comment="关联项目")
    version = Column(String(20), default="V1.0", comment="版本号")
    status = Column(String(20), default="draft", comment="draft / published / revising")
    is_latest = Column(Boolean, default=True, comment="是否最新版本")
    source_doc_id = Column(BigInteger, comment="复制来源（从模板/历史复制时）")
    rpn_threshold = Column(Integer, default=100, comment="RPN 阈值")
    remark = Column(Text)
    created_by = Column(BigInteger, nullable=False)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FmeaHierarchy(Base):
    """FMEA 结构树层级"""
    __tablename__ = "fmea_hierarchies"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    doc_id = Column(BigInteger, nullable=False, comment="FK to fmea_documents.id")
    parent_id = Column(BigInteger, comment="自引用父节点（null=根节点）")
    level_type = Column(String(50), comment="DFMEA: system/subsystem/component; PFMEA: process/step/element")
    sort_order = Column(Integer, default=0, comment="同层级排序")
    label = Column(String(200), nullable=False, comment="节点名称/描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FmeaItem(Base):
    """FMEA 项（功能/失效模式/原因/控制/S/O/D/RPN）"""
    __tablename__ = "fmea_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    doc_id = Column(BigInteger, nullable=False, comment="FK to fmea_documents.id")
    hierarchy_id = Column(BigInteger, nullable=False, comment="FK to fmea_hierarchies.id")
    function_desc = Column(Text, nullable=False, comment="功能/要求描述")
    failure_mode = Column(Text, nullable=False, comment="失效模式")
    failure_effect = Column(Text, nullable=False, comment="失效影响")
    failure_cause = Column(Text, nullable=False, comment="失效原因")
    current_control_prevent = Column(Text, comment="现行控制（预防）")
    current_control_detect = Column(Text, comment="现行控制（探测）")
    severity = Column(Integer, nullable=False, comment="S 严重度 1-10")
    occurrence = Column(Integer, nullable=False, comment="O 频度 1-10")
    detection = Column(Integer, nullable=False, comment="D 探测度 1-10")
    rpn = Column(Integer, nullable=False, comment="RPN = S × O × D")
    is_high_risk = Column(Boolean, default=False, comment="是否高风险（RPN>=阈值 或 S>=9）")
    is_critical_process = Column(Boolean, default=False, comment="是否是关键工序（PFMEA 联动 M03）")
    recommended_action = Column(Text, comment="建议措施")
    status = Column(String(20), default="open", comment="open / in_progress / completed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FmeaAction(Base):
    """FMEA 整改措施"""
    __tablename__ = "fmea_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    item_id = Column(BigInteger, nullable=False, comment="FK to fmea_items.id")
    action_desc = Column(Text, nullable=False, comment="措施描述")
    responsible_id = Column(BigInteger, nullable=False, comment="责任人")
    target_date = Column(Date, comment="目标完成日期")
    status = Column(String(20), default="open", comment="open / in_progress / completed / verified")
    completed_at = Column(DateTime(timezone=True), comment="实际完成时间")
    re_severity = Column(Integer, comment="复评 S")
    re_occurrence = Column(Integer, comment="复评 O")
    re_detection = Column(Integer, comment="复评 D")
    re_rpn = Column(Integer, comment="复评 RPN")
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ControlPlan(Base):
    """控制计划（从 FMEA 自动生成）"""
    __tablename__ = "control_plans"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    fmea_doc_id = Column(BigInteger, nullable=False, comment="FK to fmea_documents.id")
    fmea_item_id = Column(BigInteger, nullable=False, comment="FK to fmea_items.id")
    process_id = Column(BigInteger, comment="关联工序")
    control_item = Column(String(300), nullable=False, comment="控制项名称")
    control_method = Column(String(200), nullable=False, comment="控制方法（检验/监测/防错...）")
    frequency = Column(String(100), comment="控制频次")
    responsible = Column(String(200), comment="责任人/角色")
    specification = Column(Text, comment="规格要求")
    source = Column(String(20), default="auto", comment="auto（自动生成）/ manual（手动添加）")
    status = Column(String(20), default="draft", comment="draft / active / obsolete")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
