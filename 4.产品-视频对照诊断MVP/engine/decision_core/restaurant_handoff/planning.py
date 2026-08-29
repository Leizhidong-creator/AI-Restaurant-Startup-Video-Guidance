from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contracts import QuestionCandidate, SessionSnapshot


@dataclass(frozen=True)
class QuestionSelection:
    fact_key: str
    question: str
    rationale: str


class QuestionPlanner(Protocol):
    def select(
        self,
        snapshot: SessionSnapshot,
        candidates: Sequence[QuestionCandidate],
    ) -> QuestionSelection: ...


class CallableModelQuestionPlanner:
    """Use an injected language-model callable for semantic question selection.

    The callable receives a JSON-only prompt and must return a mapping with
    ``fact_key``, ``question`` and ``rationale``. Keeping model transport outside
    this package avoids hard-coding a provider or leaking credentials.
    """

    def __init__(self, model_call: Callable[[str], Mapping[str, Any]]) -> None:
        self.model_call = model_call

    def select(
        self,
        snapshot: SessionSnapshot,
        candidates: Sequence[QuestionCandidate],
    ) -> QuestionSelection:
        if not candidates:
            raise ValueError("at least one question candidate is required")
        candidate_map = {item.fact_key: item for item in candidates}
        prompt = self._prompt(snapshot, candidates)
        value = self.model_call(prompt)
        fact_key = str(value.get("fact_key", ""))
        if fact_key not in candidate_map:
            raise ValueError("model selected a fact_key outside the candidate set")
        chosen = candidate_map[fact_key]
        question = str(value.get("question") or chosen.question).strip()
        rationale = str(value.get("rationale", "")).strip()
        if not question or not rationale:
            raise ValueError("model selection must include question and rationale")
        return QuestionSelection(fact_key=fact_key, question=question, rationale=rationale)

    @staticmethod
    def _prompt(
        snapshot: SessionSnapshot,
        candidates: Sequence[QuestionCandidate],
    ) -> str:
        payload = {
            "task": (
                "Choose exactly one next question whose answer is most likely to change the next "
                "safe action or final restaurant-business conclusion. Do not choose by list order. "
                "Prefer resolving contradictions and irreversible risk. Return JSON only."
            ),
            "stage": snapshot.stage.value,
            "facts": {
                key: {
                    "value": snapshot.value(key),
                    "kind": snapshot.fact(key).kind.value if snapshot.fact(key) else None,
                    "verification": snapshot.fact(key).verification.value if snapshot.fact(key) else None,
                }
                for key in snapshot.facts
            },
            "hypotheses": [
                {
                    "code": item.code,
                    "statement": item.statement,
                    "supporting_evidence_ids": item.supporting_evidence_ids,
                    "counter_evidence_ids": item.counter_evidence_ids,
                    "missing_fact_keys": item.missing_fact_keys,
                }
                for item in snapshot.hypotheses
            ],
            "candidates": [
                {
                    "fact_key": item.fact_key,
                    "question": item.question,
                    "decision_impact": item.decision_impact,
                    "evidence_request": item.evidence_request,
                }
                for item in candidates
            ],
            "output_schema": {
                "fact_key": "one candidate fact_key",
                "question": "one concise Chinese question",
                "rationale": "why this answer can change the decision",
            },
        }
        return json.dumps(payload, ensure_ascii=False)


