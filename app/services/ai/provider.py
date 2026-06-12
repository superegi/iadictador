import os
from dataclasses import dataclass
from typing import Any


class AIProviderError(RuntimeError):
    pass


@dataclass
class AIProviderConfig:
    task: str
    provider: str
    model: str
    api_key: str = ""
    store: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ["1", "true", "yes", "y", "si", "sí"]


def get_ai_config(task: str) -> AIProviderConfig:
    task_key = task.strip().upper()

    provider = (
        os.getenv(f"IAD_AI_PROVIDER_{task_key}")
        or os.getenv("IAD_AI_PROVIDER_DEFAULT")
        or os.getenv("AI_PROVIDER")
        or "openai"
    ).strip().lower()

    model = (
        os.getenv(f"IAD_AI_MODEL_{task_key}")
        or os.getenv("IAD_AI_MODEL_DEFAULT")
        or os.getenv("OPENAI_MODEL")
        or "gpt-4.1-mini"
    ).strip()

    api_key = (
        os.getenv(f"IAD_AI_API_KEY_{task_key}")
        or os.getenv("IAD_AI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()

    store = _env_bool(f"IAD_AI_STORE_{task_key}", _env_bool("OPENAI_STORE", False))

    return AIProviderConfig(
        task=task_key,
        provider=provider,
        model=model,
        api_key=api_key,
        store=store,
    )


def get_ai_provider(task: str):
    config = get_ai_config(task)

    if config.provider in ["openai", "gpt"]:
        from app.services.ai.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config)

    if config.provider in ["dummy", "none", "off", "local"]:
        from app.services.ai.providers.dummy_provider import DummyProvider
        return DummyProvider(config)

    raise AIProviderError(f"Proveedor IA no soportado para {config.task}: {config.provider}")


def ai_json_call(
    task: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    json_schema: dict[str, Any],
) -> dict[str, Any]:
    provider = get_ai_provider(task)
    return provider.json_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_name=schema_name,
        json_schema=json_schema,
    )
