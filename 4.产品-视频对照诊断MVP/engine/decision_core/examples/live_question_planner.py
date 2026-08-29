from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    CallableModelQuestionPlanner,
    OpenAICompatibleJsonClient,
    SessionSnapshot,
    Stage,
    RestaurantSkillProvider,
)


def main() -> None:
    client = OpenAICompatibleJsonClient.from_env()
    provider = RestaurantSkillProvider(
        question_planner=CallableModelQuestionPlanner(client)
    )
    directive = provider.next_directive(
        SessionSnapshot(
            stage=Stage.PLANNED_OPENING,
            facts={
                "payment_or_signature_within_72h": False,
                "deposit_paid": False,
                "funding_type": "自有",
            },
        )
    )
    print(json.dumps(directive.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


