"""LangGraph state for one research run (architecture §10).

Research data only: no API keys, credentials, cookies, tokens or headers. Runtime dependencies
(LLM gateway, tools, trace recorder) are bound to the graph nodes instead.
"""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict

from app.schemas.contracts import (
    DocumentAnalysis,
    FinalReview,
    ReplanningRequest,
    ResearchPlan,
    ResearchRequest,
    SearchRequest,
    SearchResults,
    SynthesisDecision,
)
from app.tools.literature.models import Paper


class AgentFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node: str
    code: str
    message: str
    iteration: int
    paper_id: str | None = None
    fatal: bool = False


def merge_papers(left: dict[str, Paper], right: dict[str, Paper]) -> dict[str, Paper]:
    return {**left, **right}


class ResearchState(TypedDict, total=False):
    # immutable input
    request: ResearchRequest
    # updated (latest wins; history lists below keep every version)
    iteration: int
    plan: ResearchPlan
    search_request: SearchRequest
    replanning_request: ReplanningRequest | None
    route: str  # the next edge chosen by the node that just ran
    stop_reason: Literal["sufficient", "iteration_limit", "budget_limit"] | None
    status: Literal["running", "completed", "completed_with_limitations", "partial", "failed"]
    final_review: FinalReview | None
    # append-only histories
    plan_history: Annotated[list[ResearchPlan], operator.add]
    search_history: Annotated[list[SearchResults], operator.add]
    analysis_history: Annotated[list[DocumentAnalysis], operator.add]
    synthesis_history: Annotated[list[SynthesisDecision], operator.add]
    replan_history: Annotated[list[ReplanningRequest], operator.add]
    errors: Annotated[list[AgentFailure], operator.add]
    # merged by key: every paper the run has seen (str(paper_id) → Paper)
    papers: Annotated[dict[str, Paper], merge_papers]
