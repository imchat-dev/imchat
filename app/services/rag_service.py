# app/services/rag_service.py
from __future__ import annotations

import json
from typing import Optional

from langchain_core.messages import AIMessage, FunctionMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from app.adapters.vectorstores.chroma_adapter import load_or_create_chroma, retrieve_context
from app.adapters.llm.openai_provider import get_chat_llm
from app.core.config import settings
from app.core.tenant_config import ProfileConfig
from app.services.tool_service import ToolExecutionError, ToolManager


class RagService:
    """Retrieve augmented generation helper."""

    def __init__(self, session_factory=None, vector=None, llm=None, tool_manager: Optional[ToolManager] = None):
        self.session_factory = session_factory
        self._vector_cache = {}
        self.vector = vector
        self.llm = llm
        self.tool_manager = tool_manager or ToolManager()

    async def answer(
        self,
        question: str,
        tenant_id: str,
        profile_key: str,
        profile_config: ProfileConfig,
        memory_text: str = "",
    ) -> str:
        collection_name = profile_config.vector_collection
        vector = self._get_vector(collection_name)
        context_text = retrieve_context(
            vector,
            question,
            tenant_id=tenant_id,
            profile_key=profile_key,
            k=6,
        )
        if not context_text.strip():
            return "Ne demek istediginizi anlayamadim"

        base_template = profile_config.prompt_template or self._default_prompt(profile_key)
        prompt = PromptTemplate(
            input_variables=["memory", "context", "question"],
            template=base_template,
        )
        format_kwargs = {
            "memory": memory_text,
            "context": context_text,
            "question": question,
        }

        tool_specs = self.tool_manager.get_function_specs(profile_config)
        if tool_specs:
            prompt_text = prompt.format(**format_kwargs)
            prompt_text = self.tool_manager.inject_tool_instructions(prompt_text, profile_config)
            return await self._run_with_tools(
                prompt_text=prompt_text,
                tenant_id=tenant_id,
                profile_key=profile_key,
                profile_config=profile_config,
                tool_specs=tool_specs,
            )

        llm = self._get_llm()
        chain = prompt | llm | StrOutputParser()
        output = await chain.ainvoke(format_kwargs)
        return (output or "").strip()

    async def _run_with_tools(
        self,
        prompt_text: str,
        tenant_id: str,
        profile_key: str,
        profile_config: ProfileConfig,
        tool_specs,
    ) -> str:
        llm_with_tools = self._get_llm().bind(functions=tool_specs, function_call="auto")
        human_message = HumanMessage(content=prompt_text)
        ai_message = await llm_with_tools.ainvoke([human_message])

        function_call = ai_message.additional_kwargs.get("function_call") if isinstance(ai_message, AIMessage) else None
        if not function_call:
            return getattr(ai_message, "content", "").strip()

        try:
            tool_output = await self.tool_manager.execute(
                tenant_id=tenant_id,
                profile_key=profile_key,
                profile_config=profile_config,
                tool_name=function_call.get("name", ""),
                arguments_json=function_call.get("arguments", "{}"),
            )
        except (ToolExecutionError, json.JSONDecodeError) as exc:
            return f"Arac cagrisinda hata olustu: {exc}"

        function_response = FunctionMessage(
            name=function_call.get("name", "unknown"),
            content=tool_output,
        )
        followup_messages = [human_message, ai_message, function_response]
        final_llm = self._get_llm()
        final_message = await final_llm.ainvoke(followup_messages)
        return getattr(final_message, "content", "").strip()

    def _get_vector(self, collection_name: str):
        if collection_name not in self._vector_cache:
            self._vector_cache[collection_name] = load_or_create_chroma(
                settings.persist_dir,
                collection_name=collection_name,
            )
        return self._vector_cache[collection_name]

    def _get_llm(self):
        if self.llm is not None:
            return self.llm
        self.llm = get_chat_llm()
        return self.llm

    def _default_prompt(self, profile_key: str) -> str:
        templates = {
            "ogrenci": (
                "Sen ogrencilere yardim eden site rehber asistanisin. "
                "Sadece ogrenciler icin olan site kullanim bilgilerini kullanarak yanit ver.\n\n"
                "ONEMLI KURALLAR:\n"
                "1. Sadece ogrenci rehber bilgilerini kullan\n"
                "2. Ogretmen veya mudur bilgilerini asla verme\n"
                "3. Ogrenci olmayan kullanicilara 'Bu bilgi sadece ogrenciler icindir' de\n"
                "4. Yanitlarini sadece Turkce ver\n"
                "5. Dostca ve rehberlik edici bir ton kullan\n"
                "6. Adim adim aciklamalar ver\n"
                "7. Onceki konusmalari hatirla ve tutarli ol\n\n"
                "{memory}Ogrenci Site Rehberi:\n{context}\n\n"
                "Ogrenci Sorusu: {question}\n\nYanit:"
            ),
            "ogretmen": (
                "Sen ogretmenlere yardim eden site rehber asistanisin. "
                "Sadece ogretmenler icin olan site kullanim bilgilerini kullanarak yanit ver.\n\n"
                "ONEMLI KURALLAR:\n"
                "1. Sadece ogretmen rehber bilgilerini kullan\n"
                "2. Ogrenci veya mudur bilgilerini asla verme\n"
                "3. Ogretmen olmayan kullanicilara 'Bu bilgi sadece ogretmenler icindir' de\n"
                "4. Yanitlarini sadece Turkce ver\n"
                "5. Dostca ve rehberlik edici bir ton kullan\n"
                "6. Adim adim aciklamalar ver\n"
                "7. Onceki konusmalari hatirla ve tutarli ol\n\n"
                "{memory}Ogretmen Site Rehberi:\n{context}\n\n"
                "Ogretmen Sorusu: {question}\n\nYanit:"
            ),
            "yonetici": (
                "Sen mudurlere yardim eden site rehber asistanisin. "
                "Sadece mudurler icin olan site kullanim bilgilerini kullanarak yanit ver.\n\n"
                "ONEMLI KURALLAR:\n"
                "1. Sadece mudur rehber bilgilerini kullan\n"
                "2. Ogrenci veya ogretmen bilgilerini asla verme\n"
                "3. Site kullanimina dair bilgileri kullan\n"
                "4. Yanitlarini sadece Turkce ver\n"
                "5. Dostca ve rehberlik edici bir ton kullan\n"
                "6. Adim adim aciklamalar ver\n"
                "7. Onceki konusmalari hatirla ve tutarli ol\n"
                "8. Ne sorulduysa sadece ona yanit ver, ekstra bilgi verme.\n"
                "9. Dokumanda olmayan bir sey sorulduysa sadece 'Ne demek istediginizi anlayamadim' de.\n"
                "10. Uzun cevap verme, ozet yaz.\n\n"
                "{memory}Mudur Site Rehberi:\n{context}\n\n"
                "Mudur Sorusu: {question}\n\nYanit:"
            ),
        }
        return templates.get(
            profile_key,
            templates["yonetici"],
        )
