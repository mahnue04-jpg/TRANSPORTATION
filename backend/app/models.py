from pydantic import BaseModel

class ChatRequest(BaseModel):
    user_id: str
    message: str


class ResetRequest(BaseModel):
    user_id: str