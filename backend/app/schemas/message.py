from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class MessageResponse(BaseModel):
    id: int; msg_type: str; title: str; content: Optional[str] = None
    sender_id: Optional[int] = None; receiver_id: int; is_read: bool = False
    read_at: Optional[datetime] = None; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class SendMessageRequest(BaseModel):
    receiver_id: int; msg_type: str; title: str; content: Optional[str] = None
    biz_type: Optional[str] = None; biz_id: Optional[str] = None

class UnreadCountResponse(BaseModel):
    total: int
