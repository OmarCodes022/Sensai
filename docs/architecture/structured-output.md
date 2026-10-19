# Schema-constrained Ollama replies

`OllamaStructuredClient.complete(model, messages, schema)` makes a separate,
non-streaming `/api/chat` call. Pass a Pydantic `BaseModel` class as `schema`.
The adapter sends its JSON Schema in Ollama's `format` field and returns a
validated instance of that class. The caller chooses the model **per call**,
just as with `OllamaClient.stream`. It does not modify chat conversations or
append a reply to `ChatSession`.

```python
from pydantic import BaseModel

from sensai.llm.structured import OllamaStructuredClient
from sensai.core.messages import Message
from sensai.settings import Settings

class Label(BaseModel):
    name: str
    confidence: float

settings = Settings()
if settings.model is None:
    raise ValueError("Select an Ollama model with SENSAI_MODEL")

client = OllamaStructuredClient(host=settings.host, timeout=settings.timeout)
label: Label = client.complete(
    model=settings.model,
    messages=[
        Message(role="system", content="Return a label and confidence."),
        Message(role="user", content="Classify this text."),
    ],
    schema=Label,
)
```

Calls send `stream: false` and use the schema from `Label.model_json_schema()`.
The Ollama response must contain `message.content` as a nonempty JSON string.
The adapter strictly validates it with Pydantic, closes the HTTP response on
success or failure, and does not log prompts or responses. It raises
`StructuredOutputError` (a subclass of `LLMError`) for malformed response
JSON, missing/empty content, invalid content JSON, or schema mismatch.
Transport/HTTP failures raise `LLMConnectionError` or `LLMError`, with a 404
raising `ModelNotFoundError`, consistent with the streaming client.
If closing the response fails, the client raises a sanitized `LLMError`
instead of returning a successful result; an earlier response error remains
primary.

JSON-schema prompting cannot guarantee a valid model response: callers must
handle errors, and any retries, policy decisions, persistence, and session
history are their responsibility. This is only a reusable foundation for the
Structured Output (T5) feature: nothing in the CLI calls it yet, and it does
**not** implement report or calendar generation.
Tests mock `requests.post` and do not require Ollama:
`.venv/bin/python -m pytest -q tests/unit/llm/test_structured.py`.
