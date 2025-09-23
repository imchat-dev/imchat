# app/core/tenant_config.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError


class ToolConfig(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    config: Dict[str, object] = Field(default_factory=dict)


class ProfileConfig(BaseModel):
    key: str
    display_name: Optional[str] = None
    vector_collection: str
    source_paths: List[str] = Field(default_factory=list)
    prompt_template: Optional[str] = None
    summary_context: Optional[str] = None
    tools: List[ToolConfig] = Field(default_factory=list)


class TenantConfig(BaseModel):
    tenant_id: str
    default_profile: str
    profiles: Dict[str, ProfileConfig]

    def get_profile(self, profile_key: str) -> ProfileConfig:
        try:
            return self.profiles[profile_key]
        except KeyError as exc:
            raise KeyError(
                f"Profile '{profile_key}' not configured for tenant '{self.tenant_id}'"
            ) from exc


class TenantConfigRegistry:
    def __init__(self, configs: Dict[str, TenantConfig]):
        self._configs = configs

    def __len__(self) -> int:
        return len(self._configs)

    def tenant_ids(self) -> List[str]:
        return list(self._configs.keys())

    def get_tenant(self, tenant_id: str) -> TenantConfig:
        try:
            return self._configs[tenant_id]
        except KeyError as exc:
            raise KeyError(f"Unknown tenant '{tenant_id}'") from exc

    def get_profile(self, tenant_id: str, profile_key: str) -> ProfileConfig:
        tenant = self.get_tenant(tenant_id)
        return tenant.get_profile(profile_key)


def _load_config_file(path: Path) -> Dict[str, TenantConfig]:
    if not path.exists():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    configs: Dict[str, TenantConfig] = {}
    for entry in raw:
        try:
            cfg = TenantConfig.model_validate(entry)
        except ValidationError as exc:  # pragma: no cover - config error should surface
            raise ValueError(f"Invalid tenant config in {path}: {exc}") from exc
        configs[cfg.tenant_id] = cfg
    return configs


def build_registry(
    config_path: Optional[str],
    fallback: Optional[Dict[str, TenantConfig]] = None,
) -> TenantConfigRegistry:
    if config_path:
        path = Path(config_path)
        configs = _load_config_file(path)
    elif fallback:
        configs = fallback
    else:
        raise ValueError("Tenant configuration is required")
    return TenantConfigRegistry(configs)
