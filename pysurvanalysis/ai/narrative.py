"""The AI Narrative: per-member summaries plus one across-members paragraph.

Two rules hold this together. The AI *summarizes* the pipeline's analysis and
never performs its own — every number it sees is one the pipeline already
computed and saved. And the across-members paragraph is qualitative by
construction: it is written from the per-member digests, combines no numbers,
and is captioned as non-statistical wherever it appears. That paragraph is the
only cross-member synthesis anywhere in the app (ADR-0001).
"""

from __future__ import annotations

from typing import Any

from .base import ProviderError, load_dotenv_if_present

ACROSS_KEY = "__across__"

SYSTEM = (
    "You are writing the results narrative for a survival-analysis report. "
    "You summarize numbers that have already been computed; you never compute, "
    "infer, or estimate anything yourself, and you never speculate about "
    "mechanism. Write plain scientific prose with no headings, no bullet lists, "
    "and no markdown. If a number you would want is absent, say the analysis "
    "does not report it rather than guessing."
)


def available_providers() -> list:
    from .anthropic_provider import AnthropicProvider
    from .openai_provider import OpenAIProvider

    load_dotenv_if_present()
    return [p for p in (AnthropicProvider(), OpenAIProvider()) if p.available()]


def get_provider(name: str | None = None):
    """The named provider, or the first configured one (``None`` if none are)."""
    from .anthropic_provider import AnthropicProvider
    from .openai_provider import OpenAIProvider

    load_dotenv_if_present()
    if name:
        provider = {"anthropic": AnthropicProvider,
                    "openai": OpenAIProvider}.get(str(name).lower())
        if provider is None:
            raise ProviderError(f"unknown AI provider {name!r}")
        return provider()
    configured = available_providers()
    return configured[0] if configured else None


# ---------------------------------------------------------------------------
# Digests — the only thing a provider ever sees
# ---------------------------------------------------------------------------

def member_digest(saved) -> str:
    """A compact text rendering of one member's saved numbers."""
    lines: list[str] = []
    es = saved.experiment_summary
    lines.append(f"Experiment type: {saved.experiment_type.label}")
    lines.append(f"Factors: {', '.join(saved.factors) or 'none'}")
    lines.append(
        f"Individuals: {es.get('n_total')}, deaths: {es.get('n_deaths')}, "
        f"censored: {es.get('n_censored')} ({es.get('pct_censored')}%), "
        f"treatments: {es.get('n_treatments')}"
    )
    if saved.exclusion_group:
        lines.append(f"Exclusion group applied: {saved.exclusion_group}")

    median = saved.median_surv
    if len(median):
        lines.append("Median survival by treatment:")
        lines.append(median.to_string(index=False))

    omnibus = saved.omnibus_lr
    if omnibus:
        lines.append(
            f"Omnibus log-rank: chi2={omnibus.get('chi2')}, "
            f"df={omnibus.get('df')}, p={omnibus.get('p_value')}"
        )

    pairwise = saved.pairwise_lr
    if len(pairwise):
        lines.append("Pairwise log-rank tests:")
        lines.append(pairwise.head(20).to_string(index=False))

    for model in saved.cox_analyses:
        if model.get("error"):
            continue
        lines.append(f"{model.get('title') or model.get('model_type')}: "
                     f"{model.get('formula')}")
        lr = model.get("lr_interaction") or {}
        if lr:
            lines.append(f"  interaction LR test: chi2={lr.get('statistic')}, "
                         f"df={lr.get('df')}, p={lr.get('p_value')}")
        coefs = model.get("coefficients")
        if coefs is not None and len(coefs):
            lines.append(coefs.head(12).to_string(index=False))
    return "\n".join(lines)


def _member_prompt(name: str, digest: str, prompt_hint: str) -> str:
    return (
        f"{prompt_hint}\n\n"
        f"Write ONE paragraph (at most 120 words) summarizing the experiment "
        f"named {name!r} from the analysis output below. Do not restate every "
        f"number — pick the ones that carry the result.\n\n"
        f"--- analysis output ---\n{digest}\n--- end ---"
    )


def _across_prompt(question: str, summaries: dict[str, str]) -> str:
    joined = "\n\n".join(f"[{name}] {text}" for name, text in summaries.items())
    return (
        "Below are independent summaries of separate experiments in one "
        "project. They were analysed separately and their numbers were never "
        "pooled.\n\n"
        f"The project's question: {question or 'not stated'}\n\n"
        "Write ONE paragraph (at most 100 words) describing where these "
        "independent experiments agree and where they disagree. This is a "
        "qualitative comparison only: do not combine, average, or "
        "meta-analyse their numbers, and do not state a combined effect or a "
        "combined p-value. If they point in different directions, say so "
        "plainly.\n\n"
        f"--- member summaries ---\n{joined}\n--- end ---"
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate(project, provider: Any = None, log=None,
             include_across: bool = True) -> dict[str, str]:
    """Narrative for a Project: ``{member_name: text, "__across__": text}``.

    Soft-fails throughout — a provider outage costs you the narrative, never
    the report.
    """
    from ..project_report import SavedAnalysis

    emit = log or (lambda _m: None)
    if provider is None or isinstance(provider, str):
        provider = get_provider(provider if isinstance(provider, str) else None)
    if provider is None:
        emit("No AI provider configured (set ANTHROPIC_API_KEY or OPENAI_API_KEY "
             "in your environment or a .env file) — skipping the narrative.")
        return {}

    out: dict[str, str] = {}
    for member in project.members():
        saved = SavedAnalysis(member)
        if not saved.exists:
            continue
        try:
            text = provider.complete(
                SYSTEM,
                _member_prompt(member.name, member_digest(saved),
                               member.type.ai_summary_prompt()),
            )
        except ProviderError as exc:
            emit(f"  [{member.name}] narrative skipped: {exc}")
            continue
        out[member.name] = text
        emit(f"  [{member.name}] narrative written ({len(text.split())} words).")

    if include_across and len(out) > 1:
        try:
            out[ACROSS_KEY] = provider.complete(
                SYSTEM, _across_prompt(project.question, out))
            emit("  across-members paragraph written.")
        except ProviderError as exc:
            emit(f"  across-members paragraph skipped: {exc}")
    return out
