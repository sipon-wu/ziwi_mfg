from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class TeamResponse(BaseModel):
    id: int; name: str; code: str; leader_id: Optional[int] = None
    department: Optional[str] = None; description: Optional[str] = None
    member_count: int = 0; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateTeamRequest(BaseModel):
    name: str; code: str; leader_id: Optional[int] = None
    department: Optional[str] = None; description: Optional[str] = None

class EmployeeResponse(BaseModel):
    id: int; user_id: Optional[int] = None; employee_no: str
    team_id: Optional[int] = None; position: Optional[str] = None
    status: str = "active"; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateEmployeeRequest(BaseModel):
    user_id: Optional[int] = None; employee_no: str
    team_id: Optional[int] = None; position: Optional[str] = None
