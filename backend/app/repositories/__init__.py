from app.repositories.base import Repository, MultiTenantRepository, SingleTenantRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.excel_import_repo import ExcelImportRepository
from app.repositories.dictionary_repo import DictionaryRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.approval_repo import ApprovalRepository
from app.repositories.organization_repo import OrganizationRepository
from app.repositories.tpm_repo import TpmRepository
from app.repositories.production_repo import ProductionRepository
# ★ RouteStepRepository 只有一个真身，在 basic_data_repo。
# production_repo 里曾有一个**同名但列全错**的副本（写 product_id/process_code/
# process_name/sort_order/workcenter/standard_time/is_critical —— route_steps
# 真实列是 route_id/operation_id/step_seq/wc_id/...），5 个方法 4 个零调用，
# 唯一在用的那个是 PFMEA 发布 500 的直接原因。已整类删除，不得再加回来。
from app.repositories.basic_data_repo import RouteStepRepository
from app.repositories.quality_repo import (
    QcPointRepository,
    InspectionStandardRepository,
    InspectionItemRepository,
    InspectionOrderRepository,
    InspectionResultRepository,
    QualityReportRepository,
)
from app.repositories.andon_repo import AndonRepository
from app.repositories.energy_repo import EnergyRepository
from app.repositories.spc_repo import (
    SpcControlLimitRepository,
    SpcDataPointRepository,
    SpcAlertRepository,
)
from app.repositories.ppap_repo import (
    PpapLevelRepository,
    PpapElementRepository,
    PpapSubmissionRepository,
    PpapSubmissionItemRepository,
)
from app.repositories.fmea_repo import (
    FmeaDocumentRepository,
    FmeaHierarchyRepository,
    FmeaItemRepository,
    FmeaActionRepository,
    ControlPlanRepository,
)

__all__ = [
    "Repository", "MultiTenantRepository", "SingleTenantRepository",
    "TenantRepository", "UserRepository", "RoleRepository",
    "ExcelImportRepository",
    "DictionaryRepository", "MessageRepository", "ApprovalRepository",
    "OrganizationRepository",
    "TpmRepository",
    "ProductionRepository", "RouteStepRepository",
    "QcPointRepository",
    "InspectionStandardRepository",
    "InspectionItemRepository",
    "InspectionOrderRepository",
    "InspectionResultRepository",
    "QualityReportRepository",
    "AndonRepository",
    "EnergyRepository",
    "SpcControlLimitRepository", "SpcDataPointRepository", "SpcAlertRepository",
    "PpapLevelRepository", "PpapElementRepository", "PpapSubmissionRepository", "PpapSubmissionItemRepository",
    "FmeaDocumentRepository", "FmeaHierarchyRepository", "FmeaItemRepository", "FmeaActionRepository",
    "ControlPlanRepository",
]
