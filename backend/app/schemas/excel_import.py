from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime

class ImportTemplateInfo(BaseModel):
    import_type: str
    template_name: str
    description: Optional[str] = None
    columns: List[dict] = []
    version: str = "1.0"

    model_config = ConfigDict(from_attributes=True)

class ExcelImportTaskResponse(BaseModel):
    id: int
    tenant_id: str
    task_name: str
    file_name: str
    file_size: Optional[int] = None
    import_type: str
    total_rows: int = 0
    success_rows: int = 0
    failed_rows: int = 0
    status: str
    error_detail: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class ImportSubmitResponse(BaseModel):
    task_id: int
    message: str = "导入任务已创建"
    status: str = "pending"

class ImportResultRow(BaseModel):
    row_number: int
    status: str  # success/failed
    message: Optional[str] = None
    data: Optional[dict] = None

class ImportResult(BaseModel):
    task_id: int
    total: int
    success: int
    failed: int
    rows: List[ImportResultRow] = []
