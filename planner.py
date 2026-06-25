"""
planner.py — Conversational task planning
Asks clarifying questions before kicking off a Claude Code build.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class Plan:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    clarifications: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | clarifying | ready | running | done


_plans: dict[str, Plan] = {}


CLARIFYING_QUESTIONS = [
    "What's the main goal of this project — what should it do when it's finished?",
    "What tech stack do you prefer, or should I choose?",
    "Any specific constraints — deadline, budget, compatibility requirements?",
]


def create_plan(description: str) -> Plan:
    plan = Plan(description=description)
    plan.status = "clarifying"
    plan.clarifications = list(CLARIFYING_QUESTIONS)
    _plans[plan.id] = plan
    return plan


def get_plan(plan_id: str) -> Optional[Plan]:
    return _plans.get(plan_id)


def answer_clarification(plan_id: str, answer: str) -> dict:
    """
    Record an answer. Returns next question or marks plan ready.
    """
    plan = _plans.get(plan_id)
    if not plan:
        return {"error": "Plan not found"}

    plan.answers.append(answer)

    remaining = len(plan.clarifications) - len(plan.answers)
    if remaining > 0:
        next_q = plan.clarifications[len(plan.answers)]
        return {"status": "clarifying", "next_question": next_q, "remaining": remaining}
    else:
        plan.status = "ready"
        return {"status": "ready", "plan_id": plan.id, "summary": build_prompt(plan)}


def build_prompt(plan: Plan) -> str:
    """Build a full Claude Code prompt from the plan + answers."""
    lines = [f"Build: {plan.description}\n"]
    for q, a in zip(plan.clarifications, plan.answers):
        lines.append(f"Q: {q}")
        lines.append(f"A: {a}\n")
    lines.append("Please scaffold the full project, write all code, and make it runnable.")
    return "\n".join(lines)


def list_plans() -> list[dict]:
    return [
        {
            "id": p.id,
            "description": p.description,
            "status": p.status,
            "answered": len(p.answers),
            "total_questions": len(p.clarifications),
        }
        for p in _plans.values()
    ]
