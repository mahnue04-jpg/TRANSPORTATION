print("MAIN.PY LOADED")
from dotenv import load_dotenv
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI


from pydantic import BaseModel

from app.database import get_connection, init_db # type: ignore

# Initialize the database when the app starts
init_db()

from app.models import ChatRequest # type: ignore
from app.weather import get_weather # type: ignore

# Use ChatRequest for chat, but a minimal model for reset
class ResetRequest(BaseModel):
    user_id: str

load_dotenv()

app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
def reset_chat(req: ResetRequest): # type: ignore
    user_id = req.user_id

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM messages WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()

    return {
        "user_id": user_id,
        "status": "memory cleared"
    }
@app.post("/api/chat")
async def chat(request: ChatRequest):
    message = request.message.lower()
    print("MESSAGE:", message)

    if "weather" in message.lower():
        try:
            city = "miami"
            if "weather in" in message.lower():
                city = message.lower().split("weather in", 1)[1].strip()
            print("CITY:", city)
            weather = get_weather(city)
            print("WEATHER RESULT:", weather)
            return {"reply": weather}
        except Exception as e:
            print("WEATHER ERROR:", str(e))
            return {"reply": f"Weather error: {str(e)}"}

    # OPENAI FALLBACK
    print("OPENAI FALLBACK")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": request.message}]
    )
    return {"reply": response.choices[0].message.content}
def reset_chat(req: ResetRequest):
    user_id = req.user_id.strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {
        "user_id": user_id,
        "status": "memory cleared"
    }