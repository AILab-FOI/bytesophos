# app/services/llm_client.py

from typing import Callable, List
from haystack.dataclasses import ChatMessage
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.utils import Secret

from app.config import GROQ_API_KEY, GROQ_API_BASE, GROQ_MODEL

def build_llm(on_chunk: Callable) -> OpenAIChatGenerator:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    return OpenAIChatGenerator(
        api_key=Secret.from_token(GROQ_API_KEY),
        api_base_url=str(GROQ_API_BASE),
        model=GROQ_MODEL,
        streaming_callback=on_chunk,
    )