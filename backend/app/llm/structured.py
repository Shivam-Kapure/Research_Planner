import json
import re

from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class OutputParseError(Exception):
    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.problem = problem


def schema_name(schema: type[BaseModel]) -> str:
    return str(getattr(schema, "schema_name", schema.__name__))


def json_instruction(schema: type[BaseModel]) -> str:
    """Provider-neutral structured-output instruction. Native JSON mode is also requested, but
    schema enforcement differs between providers, so the schema is always stated and the
    result always validated here."""
    compact = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    return (
        "Respond with a single JSON object and nothing else (no prose, no code fences). "
        f"It must validate against this JSON Schema:\n{compact}"
    )


def parse_output[T: BaseModel](text: str, schema: type[T]) -> T:
    fenced = _FENCE.match(text)
    candidate = fenced.group(1) if fenced else text.strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise OutputParseError(f"not valid JSON ({exc.msg} at position {exc.pos})") from None
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise OutputParseError(summarize_validation_error(exc)) from None


def summarize_validation_error(exc: ValidationError, limit: int = 1000) -> str:
    """Field locations and messages only; submitted values are never echoed."""
    parts = [
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    ]
    return "; ".join(parts)[:limit]
