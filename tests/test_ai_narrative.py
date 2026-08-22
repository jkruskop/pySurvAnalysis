"""The AI narrative: digests, the across-members rule, and soft failure."""

from __future__ import annotations

import pytest

from pysurvanalysis.ai import narrative
from pysurvanalysis.ai.base import Provider, ProviderError


class FakeProvider(Provider):
    """Records what it was asked; returns a deterministic paragraph."""

    def __init__(self, fail: bool = False):
        super().__init__(name="fake", env_key="FAKE_KEY", models=("fake-1",))
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def available(self) -> bool:
        return True

    def complete(self, system: str, prompt: str, max_tokens: int = 1600) -> str:
        if self.fail:
            raise ProviderError("provider is down")
        self.calls.append((system, prompt))
        return f"Summary #{len(self.calls)}."


def test_no_provider_configured_returns_nothing_and_says_why(analysed_project,
                                                             monkeypatch):
    project, _results = analysed_project
    monkeypatch.setattr(narrative, "get_provider", lambda name=None: None)
    logged: list[str] = []
    assert narrative.generate(project, log=logged.append) == {}
    assert any("No AI provider configured" in line for line in logged)


def test_one_paragraph_per_member_plus_the_across_paragraph(analysed_project):
    project, _results = analysed_project
    provider = FakeProvider()
    result = narrative.generate(project, provider=provider)
    assert set(result) == {"rep_a", "rep_b", narrative.ACROSS_KEY}
    assert len(provider.calls) == 3


def test_the_across_prompt_forbids_pooling(analysed_project):
    project, _results = analysed_project
    provider = FakeProvider()
    narrative.generate(project, provider=provider)
    _system, prompt = provider.calls[-1]
    assert "never pooled" in prompt
    assert "do not combine, average, or" in prompt
    assert "combined p-value" in prompt


def test_the_system_prompt_forbids_computing(analysed_project):
    project, _results = analysed_project
    provider = FakeProvider()
    narrative.generate(project, provider=provider)
    system, _prompt = provider.calls[0]
    assert "never compute" in system


def test_the_digest_carries_only_saved_numbers(analysed_project):
    from pysurvanalysis.project_report import SavedAnalysis

    project, _results = analysed_project
    digest = narrative.member_digest(SavedAnalysis(project.member("rep_a")))
    assert "Interaction Experiment" in digest
    assert "Omnibus log-rank" in digest
    assert "Cox factorial model" in digest


def test_a_provider_failure_never_raises(analysed_project):
    project, _results = analysed_project
    logged: list[str] = []
    assert narrative.generate(project, provider=FakeProvider(fail=True),
                              log=logged.append) == {}
    assert any("skipped" in line for line in logged)


def test_a_single_member_gets_no_across_paragraph(project):
    project.member("rep_a").run_analysis()
    result = narrative.generate(project, provider=FakeProvider())
    assert narrative.ACROSS_KEY not in result


def test_unanalysed_members_are_skipped(project):
    project.member("rep_a").run_analysis()
    result = narrative.generate(project, provider=FakeProvider())
    assert set(result) == {"rep_a"}


def test_an_unknown_provider_name_is_an_error():
    with pytest.raises(ProviderError, match="unknown AI provider"):
        narrative.get_provider("not-a-provider")
