import json
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

AgentName = Literal["planner", "search", "analysis", "synthesis", "writer"]
LiteratureSource = Literal["openalex", "semantic_scholar"]

SubQuestionId = Annotated[str, StringConstraints(pattern=r"^sq-[1-9][0-9]?$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]


class Strict(BaseModel):
    """Nested value objects: immutable, unknown fields rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Contract(Strict):
    """A versioned message exchanged between agents.

    `schema_name` identifies the contract; `schema_version` is serialised with every payload
    so stored outputs can be read back (and migrated) safely. Contracts never carry secrets,
    provider-specific fields or database internals.
    """

    schema_name: ClassVar[str]
    schema_version: Literal[1] = 1

    def canonical_json(self) -> str:
        """Deterministic serialisation (sorted keys, no whitespace) for hashing and storage."""
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )


class YearRange(Strict):
    start: int = Field(ge=1900, le=2100)
    end: int = Field(ge=1900, le=2100)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("year range start must not be after end")
        return self


class SearchFilters(Strict):
    year_range: YearRange | None = None
    study_types: list[ShortText] = Field(default_factory=list, max_length=6)
