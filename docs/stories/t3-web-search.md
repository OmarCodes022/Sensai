## Story 1

As a skincare creator, I want Sensai to look up current trends before answering, so that my content ideas reflect what people are discussing now

- When a question needs recent information, Sensai searches before answering ("Searching the web for: …" in the terminal, a web_search tool card in the web chat)
- The answer cites numbered sources, listed with their URLs under the answer
- Questions that don't need current information get no search

## Story 2

As a creator, I want search problems explained clearly, so that I'm not misled when Sensai can't search

- No results produce a clear message
- Network errors, a refused key or a provider turning the request away don't break the chat
- Without search results, Sensai doesn't invent sources
