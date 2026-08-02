from datetime import datetime
from pydantic import BaseModel
from app.models.message import MessageSender


class MessageCreate(BaseModel):
    content: str


class MessageResponse(BaseModel):
    id: str
    session_id: str
    sender: MessageSender
    content: str
    created_at: datetime

    class Config:
        from_attributes = True
