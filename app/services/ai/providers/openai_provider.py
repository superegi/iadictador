import json
from typing import Any

import requests

from app.services.ai.provider import AIProviderConfig, AIProviderError


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider:
    def __init__(self, config: AIProviderConfig):
        self.config = config

    def _extract_output_text(self, response_json: dict[str, Any]) -> str:
        if response_json.get("output_text"):
            return response_json["output_text"]

        output = response_json.get("output", [])
        parts = []

        for item in output:
            for content in item.get("content", []):
                if content.get("type") in ["output_text", "text"]:
                    text = content.get("text")
                    if text:
                        parts.append(text)

        if parts:
            return "\n".join(parts)

        raise AIProviderError(
            "No se encontró texto JSON en la respuesta IA: "
            + json.dumps(response_json, ensure_ascii=False)[:1200]
        )

    def json_call(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.config.api_key:
            raise AIProviderError("OPENAI_API_KEY no está configurada.")

        payload = {
            "model": self.config.model,
            "input": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "store": self.config.store,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                }
            },
        }

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=90,
        )

        if resp.status_code >= 400:
            raise AIProviderError(f"OpenAI API error {resp.status_code}: {resp.text[:2000]}")

        data = resp.json()
        text = self._extract_output_text(data)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"La IA no devolvió JSON válido: {exc}; texto={text[:1200]}") from exc
