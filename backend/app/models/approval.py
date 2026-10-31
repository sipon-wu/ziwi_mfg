from sqlalchemy import Column, BigInteger, String, Boolean, Integer, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE

class ApprovalTemplate(Base):
    __tablename__ = "approval_templates"
    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    name = Column(String(200), nullable=False, comment="模板名称")
    code = Column(String(100), nullable=False, comment="模板编码")
    biz_type = Column(String(50), comment="业务类型")
    form_schema = Column(JSON, comment="表单定义JSON")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ApprovalTemplateNode(Base):
    """审批模板节点（A-S7）。

    此前 `approval_templates` 只是个"名字壳子"：节点与审批人只能由发起方在
    `POST /approvals` 时通过 `approver_ids` 临时传入 —— 意味着**申请人可以自己
    指定审批人、甚至指定自己**，且没有任何"条件"概念（如金额阈值决定走几级）。

    ★审批人为什么用 `approver_type` + `approver_ref` 而不是直接存 user_id：
    写死 user_id 的话，人员一变动（离职/调岗）所有模板全部失效，且"部门经理"
    这类岗位化审批人根本没法表达。分类型存引用，发起时才解析成具体的人。

    ★条件为什么存 JSON 而不是几列：条件形态会随业务长（金额、数量、物料类型、
    供应商等级…），用固定列表达必然很快就装不下。存 JSON + 一个小的求值器，
    求不了值的条件按"不满足"处理并留审计，而不是让审批发起失败。
    """

    __tablename__ = "approval_template_nodes"
    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    template_id = Column(BigInteger, nullable=False, comment="模板ID")
    node_order = Column(Integer, nullable=False, comment="节点顺序（同级=会签）")
    # user=指定人 / role=指定角色（角色下多人时会签）/ dept=指定部门
    approver_type = Column(String(20), default="user", comment="审批人类型: user/role/dept")
    approver_ref = Column(String(100), comment="审批人引用：user存id / role存code / dept存org_id")
    node_type = Column(String(20), default="approve", comment="节点类型: approve/cc")
    condition = Column(JSON, comment="触发条件JSON，如 {field,op,value}；为空=始终启用")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ApprovalInstance(Base):
    __tablename__ = "approval_instances"
    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    template_id = Column(BigInteger, nullable=False, comment="模板ID")
    title = Column(String(200), nullable=False, comment="审批标题")
    biz_type = Column(String(50), comment="业务类型")
    biz_id = Column(String(100), comment="业务ID")
    applicant_id = Column(BigInteger, nullable=False, comment="申请人ID")
    status = Column(String(20), default="pending", comment="状态: pending/approved/rejected/canceled")
    form_data = Column(JSON, comment="表单数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ApprovalNode(Base):
    __tablename__ = "approval_nodes"
    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    approval_id = Column(BigInteger, nullable=False, comment="审批实例ID")
    node_order = Column(Integer, nullable=False, comment="节点顺序")
    approver_id = Column(BigInteger, comment="审批人ID")
    node_type = Column(String(20), default="approve", comment="节点类型: approve/cc")
    status = Column(String(20), default="pending", comment="状态: pending/approved/rejected")
    comment = Column(Text, comment="审批意见")
    operated_at = Column(DateTime(timezone=True), comment="操作时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
