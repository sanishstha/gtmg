from app.extraction.llm import LLMResponse


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, *, messages, schema, model):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, str):
            return LLMResponse(
                parsed=None,
                raw_text=item,
                tokens_in=5,
                tokens_out=1,
                model=model,
                latency_ms=25,
                error="invalid output",
            )
        parsed = schema.model_validate(item)
        return LLMResponse(
            parsed=parsed,
            raw_text=parsed.model_dump_json(),
            tokens_in=100,
            tokens_out=40,
            model=model,
            latency_ms=200,
            error=None,
        )
