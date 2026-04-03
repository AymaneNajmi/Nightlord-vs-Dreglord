import json
import logging
import os
from enum import Enum
from typing import Any, Dict

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


def _openai_outline_model() -> str:
    return os.getenv("OPENAI_MODEL_OUTLINE") or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"


def _openai_form_model() -> str:
    return os.getenv("OPENAI_MODEL_FORM") or os.getenv("OPENAI_MODEL") or "gpt-4.1"


def _anthropic_outline_model() -> str:
    return os.getenv("ANTHROPIC_MODEL_OUTLINE") or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514"


def _anthropic_form_model() -> str:
    return os.getenv("ANTHROPIC_MODEL_FORM") or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514"


def _normalize_api_key(raw_key: str) -> str:
    key = (raw_key or "").strip().strip('"').strip("'")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def _masked_key(key: str) -> str:
    cleaned = _normalize_api_key(key)
    if len(cleaned) <= 10:
        return "***"
    return f"{cleaned[:7]}...{cleaned[-3:]}"


LLM_CONFIGS: Dict[LLMProvider, Dict[str, str]] = {
    LLMProvider.OPENAI: {
        "api_key_env": "OPENAI_API_KEY",
        "outline_model": _openai_outline_model(),
        "form_model": _openai_form_model(),
    },
    LLMProvider.ANTHROPIC: {
        "api_key_env": "ANTHROPIC_API_KEY",
        "outline_model": _anthropic_outline_model(),
        "form_model": _anthropic_form_model(),
    },
}


def get_provider(provider_name: str | None) -> LLMProvider:
    raw_provider = (provider_name or os.getenv("AI_LLM_PROVIDER") or LLMProvider.OPENAI.value).strip().lower()
    try:
        return LLMProvider(raw_provider)
    except ValueError:
        logger.warning("unknown_llm_provider provider=%s fallback=openai", raw_provider)
        return LLMProvider.OPENAI


def get_available_providers() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for provider, config in LLM_CONFIGS.items():
        key = (os.getenv(config["api_key_env"]) or "").strip()
        if not key:
            continue
        providers.append(
            {
                "provider": provider.value,
                "label": "OpenAI GPT-4" if provider == LLMProvider.OPENAI else "Anthropic Claude",
                "outline_model": config["outline_model"],
                "form_model": config["form_model"],
            }
        )
    return providers


def _validate_provider_config(provider: LLMProvider, model_key: str) -> tuple[str, str]:
    config = LLM_CONFIGS[provider]
    api_key_env = config["api_key_env"]
    api_key = _normalize_api_key(os.getenv(api_key_env) or "")
    if not api_key:
        raise RuntimeError(f"{api_key_env} missing in environment for provider '{provider.value}'")
    model = config.get(model_key)
    if not model:
        raise RuntimeError(f"Missing model config '{model_key}' for provider '{provider.value}'")
    return api_key, model


def _call_openai_json_schema(
    api_key: str,
    prompt: str,
    system_prompt: str,
    schema_payload: Dict[str, Any],
    model: str,
    max_output_tokens: int,
    temperature: float,
) -> str:
    client = OpenAI(api_key=api_key, timeout=120)
    request_payload = {
        "model": model,
        "max_output_tokens": max_output_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ai_template_output",
                "schema": schema_payload,
                "strict": True,
            },
        },
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    try:
        response = client.responses.create(**request_payload)
        return response.output_text or ""
    except TypeError:
        fallback_payload = {
            "model": model,
            "max_output_tokens": max_output_tokens,
            "input": [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        "Tu dois répondre UNIQUEMENT avec un JSON strict conforme au schéma fourni."
                    ),
                },
                {"role": "user", "content": f"SCHÉMA JSON:\n{json.dumps(schema_payload, ensure_ascii=False)}"},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        response = client.responses.create(**fallback_payload)
        return response.output_text or ""


def _call_anthropic_json_schema(
    api_key: str,
    prompt: str,
    system_prompt: str,
    schema_payload: Dict[str, Any],
    model: str,
    max_output_tokens: int,
    temperature: float,
) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    system_with_schema = (
        f"{system_prompt}\n\n"
        "Respecte STRICTEMENT le schéma JSON ci-dessous. Réponds uniquement avec un objet JSON valide.\n"
        f"SCHÉMA JSON:\n{json.dumps(schema_payload, ensure_ascii=False)}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=max_output_tokens,
        temperature=temperature,
        system=system_with_schema,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"},
        ],
    )
    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    logger.info("anthropic_usage usage=%s", response.usage)
    return "{" + text.lstrip("{")


def call_llm_json(
    provider: LLMProvider,
    prompt: str,
    system_prompt: str,
    json_schema: Dict[str, Any],
    model_key: str,
    max_output_tokens: int,
    temperature: float = 0.1,
) -> str:
    api_key, model = _validate_provider_config(provider, model_key)
    logger.info(
        "llm_call provider=%s model=%s prompt_len=%s api_key=%s",
        provider.value,
        model,
        len(prompt or ""),
        _masked_key(api_key),
    )
    if provider == LLMProvider.OPENAI:
        return _call_openai_json_schema(
            api_key=api_key,
            prompt=prompt,
            system_prompt=system_prompt,
            schema_payload=json_schema,
            model=model,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
    if provider == LLMProvider.ANTHROPIC:
        try:
            return _call_anthropic_json_schema(
                api_key=api_key,
                prompt=prompt,
                system_prompt=system_prompt,
                schema_payload=json_schema,
                model=model,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            msg = str(exc)
            if "invalid x-api-key" in msg.lower():
                raise RuntimeError(
                    "Anthropic authentication failed (invalid x-api-key). "
                    "Vérifie ANTHROPIC_API_KEY (clé valide commençant par 'sk-ant-', sans guillemets ni préfixe 'Bearer')."
                ) from exc
            raise
    raise RuntimeError(f"Unsupported provider '{provider.value}'")
