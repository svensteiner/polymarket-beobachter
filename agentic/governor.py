from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .actions import ACTION_REGISTRY
from .state import ActionProposal, RunContext


class AgentGovernor:
    """Read-only governor for Sprint 1."""

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
            if not spec.read_only:
                blocked.append({
                    "action_type": proposal.action_type,
                    "reason": "non_read_only_action_blocked_in_sprint_1",
                })
                continue

            proposal.status = "APPROVED_READ_ONLY"
            approved.append(proposal)

        return {
            "approved": approved,
            "blocked": blocked,
        }

