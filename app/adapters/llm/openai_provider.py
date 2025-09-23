# app/adapters/llm/openai_provider.py
"""
LLM sağlayıcı adaptörü.
Şimdilik OpenAI (LangChain community) kullanıyoruz.
"""

from typing import Optional
from app.core.config import settings

from langchain_community.chat_models import ChatOpenAI


def get_chat_llm(temperature: float = 0.2, model: Optional[str] = None) -> ChatOpenAI:
    """
    Tek yerden Chat LLM örneği döndürür.
    - MODEL: env'den okunur; override için parametre.
    - Temperature: default 0.2 (daha deterministik).
    """
    chosen = model or settings.llm_model
    return ChatOpenAI(model=chosen, temperature=temperature)
