from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.role import Role, Permission, RolePermission
from app.models.excel_import import ExcelImportTask, ImportTemplate
from app.models.production import WorkOrder, WorkOrderStatusLog, WorkReport, ProductBom, BomSnapshot
from app.models.spc import SpcControlLimit, SpcDataPoint, SpcAlert
from app.models.ppap import PpapLevel, PpapElementTemplate, PpapSubmission, PpapSubmissionItem
from app.models.fmea import FmeaDocument, FmeaHierarchy, FmeaItem, FmeaAction, ControlPlan
from app.models.dictionary import Dictionary, DictionaryItem
from app.models.message import Message
from app.models.approval import ApprovalTemplate, ApprovalInstance, ApprovalNode
from app.models.team import Team, Employee
from app.models.tpm import EquipmentCategory, Equipment, MaintenancePlan, MaintenanceTask, SparePart, SparePartInventory
from app.models.quality import QcPointConfig, InspectionStandard, InspectionItem, InspectionOrder, InspectionResult, QualityReport
from app.models.andon import AndonCall, AndonResponse, AndonEscalationRule, AndonEscalationLog
from app.models.energy import EnergyDevice, CarbonEmissionRecord, EnergyAlert
from app.models.sync import ChangeLog, SyncConsumer
from app.models.data_collection import (
    DataSourceConfig, CollectTask, CollectDataRecord,
    IoTGateway, IoTDevice, IotDataPoint,
    ExcelImportTaskM12, ExcelImportMapping,
    LinkMonitor, LinkMonitorLog,
)
from app.models.inventory import InventoryItem
from app.models.basic_data import Operation, WorkCenter, WcEquipment, WcTeam, ProcessRoute, RouteStep, ProductRoute, Product, ProductVersion, FactoryCalendar
from app.models.wms import (
    Warehouse, WarehouseZone, WarehouseLocation,
    Material, Batch,
    Inventory, InventoryTransaction,
    ReceiptOrder, ReceiptOrderItem,
    IssueOrder, IssueOrderItem,
    InventoryCount, InventoryCountItem,
    InventoryAlert,
    MaterialRequest, MaterialRequestItem,
)
from .warehouse import *
from app.models.trial import TrialOrder, TrialRoute, TrialBom, TrialReview
from app.models.lab import LabRequest, LabTestResult, TestStandard, LabReport, LabCalibration

__all__ = [
    "Tenant", "User", "UserRole", "Role", "Permission", "RolePermission",
    "ExcelImportTask", "ImportTemplate",
    "WorkOrder", "WorkOrderStatusLog", "WorkReport", "ProductBom", "BomSnapshot",
    "SpcControlLimit", "SpcDataPoint", "SpcAlert",
    "PpapLevel", "PpapElementTemplate", "PpapSubmission", "PpapSubmissionItem",
    "FmeaDocument", "FmeaHierarchy", "FmeaItem", "FmeaAction", "ControlPlan",
    "Dictionary", "DictionaryItem", "Message",
    "ApprovalTemplate", "ApprovalInstance", "ApprovalNode",
    "Team", "Employee",
    "EquipmentCategory", "Equipment", "MaintenancePlan", "MaintenanceTask", "SparePart", "SparePartInventory",
    "QcPointConfig", "InspectionStandard", "InspectionItem", "InspectionOrder", "InspectionResult",
    "QualityReport",
    "AndonCall", "AndonResponse", "AndonEscalationRule", "AndonEscalationLog",
    "EnergyDevice", "CarbonEmissionRecord", "EnergyAlert",
    "ChangeLog", "SyncConsumer",
    "DataSourceConfig", "CollectTask", "CollectDataRecord",
    "IoTGateway", "IoTDevice", "IotDataPoint",
    "ExcelImportTaskM12", "ExcelImportMapping",
    "LinkMonitor", "LinkMonitorLog",
    "InventoryItem",
    "Operation", "WorkCenter", "WcEquipment", "WcTeam",
    "ProcessRoute", "RouteStep", "ProductRoute",
    "Product", "ProductVersion", "FactoryCalendar",
    # M20 WMS
    "Warehouse", "WarehouseZone", "WarehouseLocation",
    "Material", "Batch",
    "Inventory", "InventoryTransaction",
    "ReceiptOrder", "ReceiptOrderItem",
    "IssueOrder", "IssueOrderItem",
    "InventoryCount", "InventoryCountItem",
    "InventoryAlert",
    "MaterialRequest", "MaterialRequestItem",
    # M16 试产管理
    "TrialOrder", "TrialRoute", "TrialBom", "TrialReview",
    # M15 实验室管理
    "LabRequest", "LabTestResult", "TestStandard", "LabReport", "LabCalibration",
]
