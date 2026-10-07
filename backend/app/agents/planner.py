"""Agent 1 — Research Planner: research request (+ scope feedback) → ResearchPlan."""

import uuid

from pydantic import ValidationError

from app.agents.base import Agent, as_json
from app.llm.types import Message
from app.schemas.contracts import ReplanningRequest, ResearchPlan, ResearchRequest

SYSTEM = """You are the Research Planner agent of ResearchPilot, a multi-agent academic \
literature-review system. Your only job is to turn a research question into an explicit, \
searchable research plan. You do not search for literature and you do not write the review.

Produce:
- objective: one precise sentence.
- sub_questions: 2-6 answerable sub-questions with ids sq-1, sq-2, ...; priority 1 = must be \
answered for the review to be useful, 2-3 = supporting. Each sub-question must reuse at least \
one of your keywords.
- keywords: >= 3 search terms (concepts, populations, interventions, outcomes).
- search_strategy: how to search OpenAlex and Semantic Scholar (query style, study types, years).
- inclusion_criteria / exclusion_criteria: what evidence counts.
- year_range / study_types: only if the request or the topic requires them."""

REVISION = """This is a scope revision (plan_version {version}). The Evidence Synthesis agent \
found that the current scope cannot be answered as planned. Revise the previous plan as the \
replanning request asks (e.g. split, narrow or re-target sub-questions), keep what still works, \
and explain the change in revision_reason."""


class PlannerAgent(Agent):
    node = "planner"
    trace_agent = "planner"
    role = "planner"

    async def run(
        self,
        request: ResearchRequest,
        *,
        iteration: int,
        previous_plan: ResearchPlan | None = None,
        replanning: ReplanningRequest | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> ResearchPlan:
        version = previous_plan.plan_version + 1 if previous_plan else 1
        messages = [Message("system", SYSTEM)]
        context: dict[str, object] = {"plan_version": version, "request": request.model_dump()}
        if previous_plan and replanning:
            messages.append(Message("system", REVISION.format(version=version)))
            context["previous_plan"] = previous_plan.model_dump(mode="json")
            context["replanning_request"] = replanning.model_dump(mode="json")
        messages.append(Message("user", as_json(context)))

        draft = await self.llm(
            ResearchPlan, messages, iteration=iteration, parent_id=parent_id, max_output_tokens=1000
        )
        try:
            plan = ResearchPlan.model_validate(
                {
                    **draft.model_dump(),
                    "plan_version": version,  # versioning is owned by code, not the model
                    "revision_reason": (
                        draft.revision_reason or (replanning.scope_change if replanning else None)
                        if version > 1
                        else None
                    ),
                    "year_range": draft.year_range or _requested_years(request),
                }
            )
        except ValidationError as exc:
            await self.rt.recorder.validation(
                "planner",
                iteration=iteration,
                schema_name="research_plan",
                passed=False,
                errors=[e["msg"] for e in exc.errors(include_input=False)],
                parent_id=parent_id,
            )
            raise
        await self.rt.recorder.validation(
            "planner",
            iteration=iteration,
            schema_name="research_plan",
            passed=True,
            parent_id=parent_id,
        )
        return plan


def _requested_years(request: ResearchRequest) -> dict[str, int] | None:
    if request.year_from or request.year_to:
        return {"start": request.year_from or 1900, "end": request.year_to or 2100}
    return None
