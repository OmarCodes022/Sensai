# Documentation index

## Getting started

- [Getting started: install, configure, chat and run the tests](getting-started.md)

## Architecture

- [Overview: base chat, modules and extension points](architecture/overview.md)
- [Typed ports and test doubles](architecture/ports.md)
- [Cancellation and total deadlines](architecture/cancellation.md)
- [SQLite session, profile and fact storage](architecture/storage.md)
- [Embeddings and local vector index (foundation)](architecture/retrieval.md)
- [Schema-constrained Ollama replies (foundation)](architecture/structured-output.md)
- [Usage and privacy-safe event hooks (foundation)](architecture/telemetry.md)
- Diagram: [`diagrams/sensai-strategy-flow.drawio`](diagrams/sensai-strategy-flow.drawio),
  an editable draw.io diagram of the target blueprint, not the current
  implementation.

## Product

- [Product scope: one creator, four reviewable outputs](product/scope.md) (planned, not built)
- [Privacy and product-claim policy](product/privacy-and-claims.md) (specification, not enforced)
- [Personas: stories, manual checks and test coverage](product/personas.md)

## User stories

- [User stories: format, template and index per feature](stories/README.md)

## Operations

- [Local or remote Ollama over SSH (`sensai-remote`)](operations/remote-ollama.md)
- [Epitech mirror](operations/epitech-mirror.md)
- [Documentation site: build, deploy and local preview](operations/documentation.md)

## Task briefs (not implemented)

- [Creator-scoped filesystem permissions](tasks/filesystem-permissions.md)
- [Tool loop: calling tools and using their results (T18)](tasks/tool-loop.md)

## Evaluation

- [Adversarial testing: manual runner and attack catalogue](https://github.com/OmarCodes022/Sensai/blob/main/evals/adversarial/README.md)
- [Adversarial harness report (2026-10-10)](https://github.com/OmarCodes022/Sensai/blob/main/evals/adversarial/report.md)

## Test data

- [`tests/fixtures/`](https://github.com/OmarCodes022/Sensai/tree/main/tests/fixtures/): synthetic brand facts and claims, DMs,
  posts and engagement figures for the fictional Serein Studio; no test uses
  them yet.

## Contributing

- [Contributing: branches, commits, workflows and new documentation pages](contributing.md)
