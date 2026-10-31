# Web search

The model does not know recent events. When a question needs current information (trends,
news, recent facts), it calls the `web_search` tool, gets the top five results, answers citing
them as `[1]`, `[2]`, and Sensai lists the sources under the answer.

```text
> What skincare trends are popular this month?
Searching the web for: skincare trends October 2026
Barrier care keeps growing [1], and peptides are back [2].
Sources:
[1] 12 Skincare Trends in 2026: Barrier Care and Ingredients https://… (2026-10-12)
[2] 2026's Biggest Skincare Trends to Try Now - Vogue https://…
```

`/search <query>` shows the results directly, without asking the model (handy in a demo).

## Providers

| `SENSAI_SEARCH_PROVIDER` | What it uses | Needs |
| --- | --- | --- |
| `brave` (default when `SENSAI_SEARCH_API_KEY` is set) | the Brave Search API | an API key from Brave |
| `duckduckgo` (default otherwise) | DuckDuckGo's HTML results page | nothing |
| `off` | no web search; the tool is not offered | |

The search goes out from your computer to the provider; your chat does not, only the query.

## When it goes wrong

No results, a network error, a refused key or DuckDuckGo turning a request away all give a
clear message; the model is told search was unavailable and answers without it, and the chat
goes on. The model is told never to invent a source or a URL.

## In the web interface

The answer shows **Web sources** under it: numbered links that open in a new tab. `/search` in
the chat shows a results card.

## Limits

DuckDuckGo limits automated requests: if it turns one away, wait a moment or use a Brave key.
Results are snippets, not full pages, so check an important fact at its source.
