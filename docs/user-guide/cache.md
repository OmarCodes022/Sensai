# Semantic cache

With `SENSAI_CACHE=1`, the **first question of a session** that closely matches an earlier one is
answered at once from the cache, without calling the model:

```text
$ SENSAI_CACHE=1 sensai qwen2.5
> What is the Hydra Glow Serum for?
...the answer saved earlier...
(from cache · 97% similar to "What does Hydra Glow Serum do?" · 0.0 s)
```

- Questions are compared by the cosine similarity of their embeddings (`SENSAI_EMBED_MODEL`, default
  `nomic-embed-text`); a match needs `SENSAI_CACHE_THRESHOLD` (default `0.92`).
- Only answers given with the **same creator, model and system prompt** (persona and profile
  included) are reused: changing any of them gives a fresh answer.
- Only the first question of a session is looked up and stored: later messages depend on the
  conversation ("make it shorter"). Interrupted, failed or empty replies are never stored.
- A cached answer is added to the conversation and saved like any other.
- If embedding fails (model not pulled, Ollama down), Sensai warns once and the chat goes on without
  the cache.
- `sensai --clear-cache` empties it.
- In the web page the reply carries a "From the cache" chip with the similarity and the original
  question.

The cache file `sensai-cache.sqlite3` (`SENSAI_CACHE_FILE`) keeps questions and answers in plain text,
like the session database. It is in `.gitignore`.
