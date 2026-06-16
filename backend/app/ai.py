import os
from openai import OpenAI

_client = None
OPENAI_TIMEOUT_SECONDS = 30.0

def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=OPENAI_TIMEOUT_SECONDS)
    return _client

def ask_openai(message: str, history: list = None) -> str: # type: ignore
    """Call OpenAI with optional conversation history.

    history: list of {"role": "user"|"assistant", "content": str}
    """
    client = get_client()
    messages = list(history) if history else [] # type: ignore
    messages.append({"role": "user", "content": message}) # type: ignore
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages, # pyright: ignore[reportUnknownArgumentType]
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content # type: ignore
