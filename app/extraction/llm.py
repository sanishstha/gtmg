"""Structured model calls. One module owns the OpenAI SDK."""

from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ValidationError

from app.config import get_settings


@dataclass
class LLMResponse:
    parsed: BaseModel | None
    raw_text: str
    tokens_in: int
    tokens_out: int
    model: str
    latency_ms: int
    error: str | None = None


class StructuredLLM(Protocol):
    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        model: str,
    ) -> LLMResponse: ...


@dataclass
class AttemptResult:
    response: LLMResponse
    tokens_in: int
    tokens_out: int
    latency_ms: int
    attempts: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return self.response.parsed is not None and not self.response.error


class OpenAIStructuredClient:
    """Official SDK structured-output parse path, isolated from the rest of the app."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key if api_key is not None else get_settings().openai_api_key
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        from openai import OpenAI

        self._client = OpenAI(api_key=key)

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        model: str,
    ) -> LLMResponse:
        instructions = "\n".join(message["content"] for message in messages if message["role"] == "system")
        user_input = "\n\n".join(message["content"] for message in messages if message["role"] != "system")
        started = perf_counter()
        try:
            parsed_response = self._client.responses.parse(
                model=model,
                instructions=instructions or None,
                input=user_input,
                text_format=schema,
                temperature=0,
            )
        except Exception as exc:
            return LLMResponse(
                parsed=None,
                raw_text="",
                tokens_in=0,
                tokens_out=0,
                model=model,
                latency_ms=_elapsed_ms(started),
                error=str(exc),
            )
        usage = parsed_response.usage
        raw_text = getattr(parsed_response, "output_text", None) or ""
        parsed = parsed_response.output_parsed
        error = None
        if parsed is None:
            error = "Model returned no parsed object"
        return LLMResponse(
            parsed=parsed,
            raw_text=raw_text,
            tokens_in=usage.input_tokens if usage is not None else 0,
            tokens_out=usage.output_tokens if usage is not None else 0,
            model=model,
            latency_ms=_elapsed_ms(started),
            error=error,
        )


def complete_with_retry(
    llm: StructuredLLM,
    *,
    messages: list[dict[str, str]],
    schema: type[BaseModel],
    model: str,
) -> AttemptResult:
    """One validation retry, then the caller persists the failure."""

    errors: list[str] = []
    tokens_in = 0
    tokens_out = 0
    latency_ms = 0
    last: LLMResponse | None = None
    for attempt in range(1, 3):
        try:
            last = llm.complete(messages=messages, schema=schema, model=model)
        except ValidationError as exc:
            last = LLMResponse(
                parsed=None,
                raw_text=str(exc),
                tokens_in=0,
                tokens_out=0,
                model=model,
                latency_ms=0,
                error=str(exc),
            )
        tokens_in += last.tokens_in
        tokens_out += last.tokens_out
        latency_ms += last.latency_ms
        if last.parsed is not None and not last.error:
            return AttemptResult(
                response=last,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                attempts=attempt,
                errors=errors,
            )
        errors.append(last.error or "empty parse")
    assert last is not None
    return AttemptResult(
        response=last,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        attempts=2,
        errors=errors,
    )


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
