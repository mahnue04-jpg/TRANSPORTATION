print("MAIN.PY LOADED")
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.database import get_connection, init_db  # type: ignore
from app.models import ChatRequest  # type: ignore
from app.router import route_message  # type: ignore

init_db()

class ResetRequest(BaseModel):
    user_id: str

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/api/reset")
def reset_chat(req: ResetRequest):  # type: ignore
    user_id = req.user_id.strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"user_id": user_id, "status": "memory cleared"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    print("MESSAGE:", request.message)
    try:
        result = route_message(request.message)
        print("TOOL:", result["tool"], "RESPONSE:", result["response"])
        return {"reply": result["response"]}
    except Exception as e:
        print("ROUTER ERROR:", str(e))
        return {"reply": f"Error: {str(e)}"}
