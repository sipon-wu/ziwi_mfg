from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo
from app.repositories.dictionary_repo import DictionaryRepository
from app.schemas.dictionary import CreateDictionaryRequest, UpdateDictionaryRequest, CreateDictionaryItemRequest, UpdateDictionaryItemRequest

router = APIRouter(prefix="/api/v1/dictionaries", tags=["M00-数据字典"])

@router.get("")
async def list_dicts(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    data = await repo.list_dicts(page, page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def create_dict(
    req: CreateDictionaryRequest,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    await repo.create_dict({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}

@router.get("/{dict_id}")
async def get_dict(
    dict_id: int,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    d = await repo.get_dict(dict_id)
    if not d: raise HTTPException(404, detail={"code":"404-0000","message":"字典不存在"})
    return {"code": 0, "message": "success", "data": d}

@router.put("/{dict_id}")
async def update_dict(
    dict_id: int, req: UpdateDictionaryRequest,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    await repo.update_dict(dict_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功"}

@router.get("/code/{code}/items")
async def get_dict_items(
    code: str,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    d = await repo.get_dict_by_code(code)
    if not d: return {"code": 0, "message": "success", "data": {"items": []}}
    items = await repo.list_items(d["id"])
    return {"code": 0, "message": "success", "data": {"items": items}}

@router.post("/{dict_id}/items")
async def create_item(
    dict_id: int, req: CreateDictionaryItemRequest,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    await repo.create_item({**req.model_dump(), "dict_id": dict_id})
    return {"code": 0, "message": "创建成功"}

@router.put("/items/{item_id}")
async def update_item(
    item_id: int, req: UpdateDictionaryItemRequest,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    await repo.update_item(item_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功"}

@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository, require_auth=True)),
):
    affected = await repo.delete_item(item_id)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "字典项不存在"})
    return {"code": 0, "message": "删除成功"}
