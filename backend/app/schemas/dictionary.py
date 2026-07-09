from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class DictionaryResponse(BaseModel):
    id: int; tenant_id: str; dict_code: str; dict_name: str
    description: Optional[str] = None; is_system: bool = False; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateDictionaryRequest(BaseModel):
    dict_code: str; dict_name: str; description: Optional[str] = None

class UpdateDictionaryRequest(BaseModel):
    dict_name: Optional[str] = None; description: Optional[str] = None

class DictionaryItemResponse(BaseModel):
    id: int; dict_id: int; item_code: str; item_name: str; item_value: Optional[str] = None
    sort_order: int = 0; is_default: bool = False; status: str = "active"
    model_config = ConfigDict(from_attributes=True)

class CreateDictionaryItemRequest(BaseModel):
    item_code: str; item_name: str; item_value: Optional[str] = None
    sort_order: int = 0; is_default: bool = False

class UpdateDictionaryItemRequest(BaseModel):
    item_name: Optional[str] = None; item_value: Optional[str] = None
    sort_order: Optional[int] = None; is_default: Optional[bool] = None; status: Optional[str] = None
