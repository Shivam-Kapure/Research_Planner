"""Pure routing decisions for the conditional graph edges (unit-testable, no I/O)."""

from typing import Literal

from app.schemas.contracts.synthesis import Verdict

SynthesisRoute = Literal["writer", "replanning", "limit_reached"]
ReplanRoute = Literal["search_revision", "scope_revision"]
StopReason = Literal["sufficient", "iteration_limit", "budget_limit"]


def route_after_synthesis(
    verdict: Verdict, iteration: int, max_iterations: int, can_afford_iteration: bool
) -> tuple[SynthesisRoute, StopReason | None]:
    if verdict == "sufficient":
        return "writer", "sufficient"
    if iteration >= max_iterations:
        return "limit_reached", "iteration_limit"
    if not can_afford_iteration:
        return "limit_reached", "budget_limit"
    return "replanning", None


def route_after_replanning(kind: Literal["search_revision", "scope_revision"]) -> ReplanRoute:
    return kind
