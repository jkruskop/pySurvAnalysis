"""OpenAI provider for the AI narrative."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Provider, ProviderError


@dataclass
class OpenAIProvider(Provider):
    name: str = "openai"
    env_key: str = "OPENAI_API_KEY"
    models: tuple[str, ...] = ("gpt-5.2", "gpt-4o")

    def complete(self, system: str, prompt: str, max_tokens: int = 1600) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:  # noqa: BLE001
            raise ProviderError("the `openai` package is not installed") from exc

        if not self.api_key:
            raise ProviderError(f"{self.env_key} is not set")

        client = OpenAI(api_key=self.api_key)
        try:
            response = client.chat.completions.create(
                model=self.model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as exc:  # noqa: BLE001 - any provider failure is soft
            raise ProviderError(str(exc)) from exc
        return (response.choices[0].message.content or "").strip()
