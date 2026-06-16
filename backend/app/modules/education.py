"""Education capability module.

Handles tutoring, explanations, quizzes, homework help, study plans,
and all general educational requests using a specialist system prompt.
"""
import os
from typing import Any, cast

from openai import OpenAI

TRIGGERS = [
    "explain", "teach me", "tutor", "tutoring",
    "homework", "quiz", "study", "lesson",
    "what is", "what are", "how does", "how do",
    "definition", "define", "summarize", "summary",
    "learn", "learning", "educate", "education",
    "exam", "test prep", "study plan", "school",
    "math", "algebra", "geometry", "calculus",
    "science", "biology", "chemistry", "physics",
    "history", "geography", "english", "grammar",
    "essay", "writing help", "proofread",
    "beginner", "advanced", "step by step",
]

SYSTEM_PROMPT = """You are Amicor's Education Tutor — a patient, knowledgeable, and encouraging teacher who adapts to any level from beginner to advanced.

You can help with:
- Explaining concepts clearly (science, math, history, language, technology, and more)
- Step-by-step homework help without just giving away answers
- Creating quizzes and practice questions on any topic
- Building personalized study plans
- Summarizing lessons, chapters, or topics
- Proofreading and improving essays or writing
- Exam preparation and test-taking strategies
- Breaking down complex ideas into simple, digestible parts

Your style:
- Be conversational, warm, and encouraging — not robotic or textbook-stiff
- Always check understanding: invite follow-up questions
- Use analogies and real-world examples to make ideas stick
- When helping with homework, guide the student to the answer rather than just providing it
- Adjust your language complexity to match the user's apparent level
- Use bullet points, numbered steps, or short paragraphs for clarity
- Celebrate effort and curiosity
"""

_client = None
OPENAI_TIMEOUT_SECONDS = 30.0


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=OPENAI_TIMEOUT_SECONDS)
    return _client


def handle(message: str, history: list[dict[str, Any]] | None = None, user_id: str = "default") -> str:
    client = _get_client()
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=cast(Any, messages),
            temperature=0.7,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return f"Education module error: {str(e)}"
