from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .actions import ACTION_REGISTRY
from .state import ActionProposal, RunContext


class AgentGovernor:
    """
    Governor for agentic actions.

    Read-only actions are always approved.
    Non-read-only actions (pause_city, tighten_risk) are approved and executed
    by ActionExecutor — effects are written to JSON files, never to live config.
    """

    def validate(self, proposals: Iterable[ActionProposal], context: RunContext) -> Dict[str, List[Any]]:
        approved: List[ActionProposal] = []
        blocked: List[Dict[str, Any]] = []

        for proposal in proposals:
            spec = ACTION_REGISTRY.get(proposal.action_type)
            if spec is None:
                blocked.append({
                    "action_type": proposal.action_type,
                    "reason": "action_not_registered",
                })
                continue

            proposal.status = "APPROVED_READ_ONLY" if spec.read_only else "APPROVED"
            approved.append(proposal)

        return {
            "approved": approved,
            "blocked": blocked,
        }

