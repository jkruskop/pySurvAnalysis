"""Anthropic provider for the AI narrative."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Provider, ProviderError


@dataclass
class AnthropicProvider(Provider):
    name: str = "anthropic"
    env_key: str = "ANTHROPIC_API_KEY"
    models: tuple[str, ...] = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")

    def complete(self, system: str, prompt: str, max_tokens: int = 1600) -> str:
        try:
            import anthropic
        except ImportError as exc:  # noqa: BLE001
            raise ProviderError("the `anthropic` package is not installed") from exc

        if not self.api_key:
            raise ProviderError(f"{self.env_key} is not set")

        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                # Summarising numbers that are already computed needs no deep
                # reasoning, and low effort keeps a per-member narrative cheap.
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - any provider failure is soft
            raise ProviderError(str(exc)) from exc

        if response.stop_reason == "refusal":
            raise ProviderError("the model declined to summarize this analysis")
        return "".join(b.text for b in response.content if b.type == "text").strip()
