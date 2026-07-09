import json
import os
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from fastapi.responses import Response
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.excel_import_repo import ExcelImportRepository
from app.services.excel_import_service import ExcelImportService

router = APIRouter(prefix="/api/v1/excel-import", tags=["M12-数据采集"])


@router.get("/templates")
async def list_templates(
    repo: ExcelImportRepository = Depends(get_tenant_repo(ExcelImportRepository, require_auth=True)),
):
    svc = ExcelImportService(repo)
    data = await svc.list_templates()
    return {"code": 0, "message": "success", "data": data}


@router.get("/templates/{import_type}/download")
async def download_template(import_type: str):
    svc = ExcelImportService(None)
    file_bytes = svc.generate_template_file(import_type)
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{import_type}_template.xlsx"'}
    )


@router.get("/tasks")
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    import_type: str = Query(None),
    status: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: ExcelImportRepository = Depends(get_tenant_repo(ExcelImportRepository)),
):
    svc = ExcelImportService(repo)
    data = await svc.list_tasks(page, page_size, import_type, status)
    return {"code": 0, "message": "success", "data": data}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    repo: ExcelImportRepository = Depends(get_tenant_repo(ExcelImportRepository, require_auth=True)),
):
    svc = ExcelImportService(repo)
    data = await svc.get_task(task_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/tasks")
async def create_import_task(
    import_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    repo: ExcelImportRepository = Depends(get_tenant_repo(ExcelImportRepository)),
):
    # 保存上传文件
    content = await file.read()
    svc = ExcelImportService(repo)

    # 解析校验
    result = svc.parse_and_validate(import_type, content)

    # 创建导入任务
    upload_dir = "uploads/imports"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{uuid.uuid4().hex}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    task_data = {
        "tenant_id": current_user.get("tenant_id", "default"),
        "task_name": f"导入_{import_type}_{file.filename}",
        "file_name": file.filename,
        "file_path": file_path,
        "file_size": len(content),
        "import_type": import_type,
        "total_rows": result["total"],
        "success_rows": len(result["rows"]),
        "failed_rows": len(result["errors"]),
        "operator_id": current_user["id"],
        "status": "completed" if not result["errors"] else "failed",
    }
    if result["errors"]:
        task_data["error_detail"] = json.dumps(result["errors"], ensure_ascii=False)

    task = await svc.create_import_task(task_data)
    return {
        "code": 0,
        "message": "导入任务处理完成",
        "data": {
            "task_id": task["task_id"],
            "status": task_data["status"],
            "total": result["total"],
            "success": len(result["rows"]),
            "failed": len(result["errors"]),
            "errors": result["errors"],
        }
    }
