from app.services.ai.provider import AIProviderConfig


class DummyProvider:
    def __init__(self, config: AIProviderConfig):
        self.config = config

    def json_call(self, system_prompt: str, user_prompt: str, schema_name: str, json_schema: dict):
        return {
            "templates": [],
            "global_warnings": [
                "Proveedor IA dummy/local activo. Se usará parser local."
            ],
        }
