# app/services/rag_service.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, FunctionMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from app.adapters.vectorstores.chroma_adapter import load_or_create_chroma, retrieve_context
from app.adapters.llm.openai_provider import get_chat_llm
from app.core.config import settings
# from app.services.tool_service import ToolExecutionError, ToolManager  # Tool calling disabled

import uuid


@dataclass
class AnswerResult:
    text: str
    files: Optional[Dict[str, Any]] = None


class RagService:
    """Retrieve augmented generation helper."""

    def __init__(self, session_factory=None, vector=None, llm=None, tool_manager=None):  # Tool calling disabled
        self.session_factory = session_factory
        self._vector_cache = {}
        self.vector = vector
        self.llm = llm
        # self.tool_manager = tool_manager or ToolManager()  # Tool calling disabled

    async def answer(
        self,
        question: str,
        tenant_id: str,
        memory_text: str = "",
    ) -> AnswerResult:
        # Use tenant_id as collection name directly
        collection_name = tenant_id
        vector = self._get_vector(collection_name)
        context_text = retrieve_context(
            vector,
            question,
            tenant_id=tenant_id,
            k=6,
        )
        if not context_text.strip():
            return AnswerResult(text="Ne demek istediginizi anlayamadim")

        base_template = self._default_prompt()
        prompt = PromptTemplate(
            input_variables=["memory", "context", "question"],
            template=base_template,
        )
        format_kwargs = {
            "memory": memory_text,
            "context": context_text,
            "question": question,
        }

        # Tool calling disabled - skip tool processing
        # tool_specs = self.tool_manager.get_function_specs(profile_config)
        # if tool_specs:
        #     prompt_text = prompt.format(**format_kwargs)
        #     prompt_text = self.tool_manager.inject_tool_instructions(prompt_text, profile_config)
        #     return await self._run_with_tools(
        #         prompt_text=prompt_text,
        #         tenant_id=tenant_id,
        #         tool_specs=tool_specs,
        #     )

        llm = self._get_llm()
        chain = prompt | llm | StrOutputParser()
        output = await chain.ainvoke(format_kwargs)
        return AnswerResult(text=(output or "").strip())

    async def _run_with_tools(
        self,
        prompt_text: str,
        tenant_id: str,
        tool_specs,
    ) -> AnswerResult:
        
        llm_with_tools = self._get_llm().bind(functions=tool_specs, function_call="auto")
        human_message = HumanMessage(content=prompt_text)
        ai_message = await llm_with_tools.ainvoke([human_message])
        # Yeni OpenAI tool_calls semantigini once isle, yoksa eski function_call yoluna dus
        tool_calls = []
        if isinstance(ai_message, AIMessage):
            tool_calls = (
                ai_message.additional_kwargs.get("tool_calls")
                or getattr(ai_message, "tool_calls", [])
                or []
            )

        if tool_calls:
            followup_messages = [human_message, ai_message]
            last_tool_output = None
            for idx, call in enumerate(tool_calls, 1):
                fn = (call.get("function") or {})
                name = fn.get("name") or call.get("name") or ""
                arguments_json = fn.get("arguments") or call.get("arguments") or "{}"
                try:
                    tool_output = await self.tool_manager.execute(
                        tenant_id=tenant_id,
                        tool_name=name,
                        arguments_json=arguments_json,
                    )
                    last_tool_output = tool_output
                except (ToolExecutionError, json.JSONDecodeError) as exc:
                    return AnswerResult(text=f"Arac cagrisinda hata olustu: {exc}")

                followup_messages.append(FunctionMessage(name=name, content=tool_output))

            final_llm = self._get_llm()
            final_message = await final_llm.ainvoke(followup_messages)
            content = getattr(final_message, "content", "").strip()
            if content:
                content = self._format_download_links(content)
            attachments = self._extract_file_attachment(last_tool_output or "")
            if not content and attachments:
                content = "Raporu hazirladim."
            return AnswerResult(text=content, files=attachments)

        function_call = ai_message.additional_kwargs.get("function_call") if isinstance(ai_message, AIMessage) else None
        if not function_call:
            content = getattr(ai_message, "content", "").strip()
            attachment = None
            if content:
                # Try to extract a direct report URL if model answered with a link
                attachment = self._extract_url_attachment(content)
                content = self._format_download_links(content)
            return AnswerResult(text=content, files=attachment)

        try:
            tool_output = await self.tool_manager.execute(
                tenant_id=tenant_id,
                tool_name=function_call.get("name", ""),
                arguments_json=function_call.get("arguments", "{}"),
            )
        except (ToolExecutionError, json.JSONDecodeError) as exc:
            return AnswerResult(text=f"Arac cagrisinda hata olustu: {exc}")

        attachments = self._extract_file_attachment(tool_output)
        function_response = FunctionMessage(
            name=function_call.get("name", "unknown"),
            content=tool_output,
        )
        followup_messages = [human_message, ai_message, function_response]
        final_llm = self._get_llm()
        final_message = await final_llm.ainvoke(followup_messages)
        content = getattr(final_message, "content", "").strip()
        if content:
            content = self._format_download_links(content)
        elif attachments:
            content = "Raporu hazirladim."
        return AnswerResult(text=content, files=attachments)

    def _extract_file_attachment(self, tool_output: str) -> Optional[Dict[str, Any]]:
        try:
            payload = json.loads(tool_output or "{}")
        except (TypeError, json.JSONDecodeError):
            return None

        downloads = payload.get("downloads")
        links: Optional[Dict[str, Any]] = None
        if isinstance(downloads, dict):
            links_candidate = downloads.get("links")
            if isinstance(links_candidate, dict):
                links = links_candidate
        if links is None and isinstance(payload.get("links"), dict):
            links = payload["links"]

        candidate_entry: Optional[Dict[str, Any]] = None
        if isinstance(links, dict):
            for key in ("pdf", "PDF"):
                entry = links.get(key)
                if isinstance(entry, dict):
                    candidate_entry = entry
                    break
            if candidate_entry is None:
                for entry in links.values():
                    if isinstance(entry, dict) and entry.get("content_base64"):
                        candidate_entry = entry
                        break

        if candidate_entry is None and isinstance(payload.get("pdf"), str):
            pdf_data = payload["pdf"].strip()
            if pdf_data:
                return {
                    "name": "rapor.pdf",
                    "type": "pdf",
                    "encoding": "base64",
                    "data": pdf_data,
                }
            return None

        if not candidate_entry:
            return None

        # ...candidate_entry bulunduktan sonra:
        download_url = candidate_entry.get("download_url")
        if isinstance(download_url, str) and download_url.strip():
            name = candidate_entry.get("file_name") or "rapor.pdf"
            raw_type = (candidate_entry.get("content_type") or "application/pdf").lower()
            content_type = "application/pdf" if "pdf" in raw_type else raw_type or "application/octet-stream"
            # ChatResponse FileAttachment schema'sÄ±na uygun format:
            return {
                "name": str(name),
                "type": content_type,
                "encoding": "url",
                "data": download_url.strip(),
            }

        # (mevcut base64 geri dÃ¶nÃ¼ÅŸÃ¼ altta aynen kalsÄ±n)
        data = candidate_entry.get("content_base64")
        if not isinstance(data, str) or not data.strip():
            return None

        name = candidate_entry.get("file_name") or "rapor.pdf"
        raw_type = (candidate_entry.get("content_type") or "pdf").strip().lower()
        content_type = "pdf" if "pdf" in raw_type else raw_type or "pdf"
        encoding = candidate_entry.get("encoding") or "base64"
        return {
            "name": str(name),
            "type": str(content_type),
            "encoding": str(encoding),
            "data": data.strip(),
        }

    def _format_download_links(self, text: str) -> str:
        # Normalize any sandbox prefixes first
        text = text.replace("sandbox:/app", "").replace("sandbox:", "")

        # Replace markdown links pointing to /downloads/... with normalized labels
        def normalize_label(match) -> str:
            url = match.group("url")
            return f"[rapor.pdf]({url})"

        text = re.sub(
            r"\[[^\]]*\]\((?P<url>(?:/downloads/[^)]+|https?://[^)]+?/downloads/[^)]+))\)",
            normalize_label,
            text,
        )

        # Sadece satÄ±r baÅŸÄ±nda ya da boÅŸluktan sonra gelen "Ã§Ä±plak" /downloads/... metnini sadeleÅŸtir.
        text = re.sub(r"(?:^|(?<=\s))/downloads/[A-Za-z0-9._%\-]+", "rapor.pdf", text)

        # Replace any external rapor URLs with plain filename
        text = re.sub(
            r"\[[^\]]*\]\((https?://[^)]+?/rapor/[^)]+)\)",
            "rapor.pdf",
            text,
        )
        text = re.sub(
            r"(?<!\()(https?://[^\s)]+?/rapor/[^\s)]+)",
            "rapor.pdf",
            text,
        )

        # Fallback phrasing
        text = text.replace("Buradan indirebilirsiniz", "rapor.pdf")
        return text

    def _extract_url_attachment(self, text: str) -> Optional[Dict[str, Any]]:
        # Find first external rapor URL in markdown or plain text
        md_match = re.search(r"\((https?://[^)]+?/rapor/[^)]+)\)", text)
        if md_match:
            url = md_match.group(1).strip()
            return {"name": "rapor.pdf", "type": "application/pdf", "encoding": "url", "data": url}
        plain_match = re.search(r"(https?://[^\s)]+?/rapor/[^\s)]+)", text)
        if plain_match:
            url = plain_match.group(1).strip()
            return {"name": "rapor.pdf", "type": "application/pdf", "encoding": "url", "data": url}
        return None

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

    def _default_prompt(self) -> str:
        # Use a generic template since we don't have user roles anymore
        return (
            "Sen site kullanicilarina yardim eden rehber asistanisin. "
            "Verilen dokumanlardaki bilgileri kullanarak yanit ver.\n\n"
            "ONEMLI KURALLAR:\n"
            "1. Sadece verilen dokumanlardaki bilgileri kullan\n"
            "2. Bilmedigin konularda 'Bu konuda yeterli bilgim yok' de\n"
            "3. Detayli ve aciklayici cevaplar ver\n"
            "4. Adim adim rehberlik et\n"
            "5. Turkce cevap ver\n"
            "6. Kisa ve net cevaplar ver\n\n"
            "{memory}Site Rehberi:\n{context}\n\n"
            "Kullanici Sorusu: {question}\n\nYanit:"
        )











