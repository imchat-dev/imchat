# app/services/tool_service.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.tenant_config import ProfileConfig, ToolConfig


class ToolExecutionError(Exception):
    """Raised when a tool cannot be executed."""


@dataclass
class ToolContext:
    tenant_id: str
    profile_key: str
    tool_config: ToolConfig


class BaseTool:
    name: str
    description: str
    parameters: Dict[str, object]

    async def run(self, *, arguments: Dict[str, object], context: ToolContext) -> str:
        raise NotImplementedError

    def function_spec(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class CurrentDateTimeTool(BaseTool):
    name = "current_datetime"
    description = "Mevcut tarihi ve saati UTC olarak dondurur."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self, *, arguments: Dict[str, object], context: ToolContext) -> str:
        now = datetime.now(timezone.utc)
        return json.dumps(
            {
                "utc_datetime": now.isoformat(),
                "tenant_id": context.tenant_id,
                "profile_key": context.profile_key,
            }
        )


class ToolManager:
    """Maps profile tool configs to executable Python callables."""

    def __init__(self):
        self._registry: Dict[str, BaseTool] = {
            CurrentDateTimeTool.name: CurrentDateTimeTool(),
        }

    def get_function_specs(self, profile_config: ProfileConfig) -> List[Dict[str, object]]:
        specs: List[Dict[str, object]] = []
        for tool in profile_config.tools:
            if not tool.enabled:
                continue
            impl = self._registry.get(tool.name)
            if impl is not None:
                specs.append(impl.function_spec())
        return specs

    def describe_tools(self, profile_config: ProfileConfig) -> str:
        descriptions = []
        for tool in profile_config.tools:
            if not tool.enabled:
                continue
            impl = self._registry.get(tool.name)
            if impl is not None:
                descriptions.append(f"- {tool.name}: {tool.description or impl.description}")
        return "\n".join(descriptions)

    def inject_tool_instructions(self, prompt_text: str, profile_config: ProfileConfig) -> str:
        tool_description = self.describe_tools(profile_config)
        if not tool_description:
            return prompt_text
        instructions = (
            "\n\nKullanilabilir araclar:\n"
            f"{tool_description}\n"
            "Bir arac gerekli ise fonksiyon cagrisi yapabilirsin."
        )
        return prompt_text + instructions

    async def execute(
        self,
        *,
        tenant_id: str,
        profile_key: str,
        profile_config: ProfileConfig,
        tool_name: str,
        arguments_json: str,
    ) -> str:
        impl = self._registry.get(tool_name)
        if impl is None:
            raise ToolExecutionError(f"Tanimlanmayan arac: {tool_name}")

        tool_cfg = self._find_tool_config(profile_config, tool_name)
        if tool_cfg is None or not tool_cfg.enabled:
            raise ToolExecutionError(f"Arac etkin degil: {tool_name}")

        try:
            arguments = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("Gecersiz arac argumanlari") from exc

        context = ToolContext(
            tenant_id=tenant_id,
            profile_key=profile_key,
            tool_config=tool_cfg,
        )
        return await impl.run(arguments=arguments, context=context)

    def build_prompt_appendix(self, profile_config: ProfileConfig) -> str:
        if not any(tool.enabled for tool in profile_config.tools):
            return ""
        return "\n\nKullanilabilir araclar ile calisabilir ve gerekirse arac ciktisini kullanarak son cevabi olusturabilirsin."

    def _find_tool_config(self, profile_config: ProfileConfig, tool_name: str) -> Optional[ToolConfig]:
        for tool in profile_config.tools:
            if tool.name == tool_name:
                return tool
        return None
