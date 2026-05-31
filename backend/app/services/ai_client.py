from openai import AsyncOpenAI

from app.core.config import Settings


class AIClientFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def openai(self) -> AsyncOpenAI | None:
        if not self.settings.openai_api_key:
            return None
        return AsyncOpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)

    def deepseek(self) -> AsyncOpenAI | None:
        if not self.settings.deepseek_api_key:
            return None
        return AsyncOpenAI(api_key=self.settings.deepseek_api_key, base_url=self.settings.deepseek_base_url)

