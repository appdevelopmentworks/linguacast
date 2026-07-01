"""Term glossary for cross-segment consistency.

v0.1 holds a simple term map that is injected into general-model prompts so the
same source term is rendered the same way throughout a long transcript.
Automatic term extraction is a future enhancement. TranslateGemma does not take
a glossary (it is not instructable), so this only affects general models.
"""

from __future__ import annotations


class Glossary:
    def __init__(self, terms: dict[str, str] | None = None) -> None:
        self.terms: dict[str, str] = dict(terms or {})

    def add(self, source_term: str, target_term: str) -> None:
        self.terms[source_term] = target_term

    def format_for_prompt(self) -> str | None:
        if not self.terms:
            return None
        return "\n".join(f"- {src}: {dst}" for src, dst in self.terms.items())
