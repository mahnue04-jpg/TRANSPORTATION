import os
from openai import OpenAI

_client = None

def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client

def ask_openai(message: str, history: list = None) -> str:
    """Call OpenAI with optional conversation history.

    history: list of {"role": "user"|"assistant", "content": str}
    """
    client = get_client()
    messages = list(history) if history else []
    messages.append({"role": "user", "content": message})
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )
    return response.choices[0].message.content
