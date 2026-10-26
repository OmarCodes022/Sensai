# User stories

The subject requires at least two user stories for every implemented feature.
Stories are the contract between a feature and the real use case it serves:
each one names a type of user, an action and an outcome, followed by
acceptance criteria that someone can observe (and ideally check with a test).

Team rule: the feature's implementer drafts the stories; another team member
reviews them (user need, failure cases, linked tests) before the feature is
claimed as done.

## Template

```text
### Story N: <short title>

As a <type of user>, I want to <action>, so that <outcome>.

Acceptance criteria:
1. <observable behavior: success case>
2. <observable behavior: edge or failure case>
3. <observable behavior: linked test or demo>
```

Add, per feature: the catalogue ID and name, the drafting lead, the reviewer,
and the review status (draft or reviewed).

## Index of implemented features

Only features implemented in the code are listed; see the
[README feature list](../../README.md#features).

| Feature | Stories | Status |
| --- | --- | --- |
| B1 Functional CLI chatbot (base chat) | — | **Stories needed** |
| A5 Persona | [3 stories in the persona guide](../product/personas.md#story-1-choose-a-role-for-the-activity) | Draft, not independently reviewed |
| M1 Session Persistence & Profiles | — | **Stories needed** |
| M2 Token Budgeting & Semantic Compression | [2 stories](m2-context-budget.md) | Draft, not independently reviewed |

Partial foundations (embeddings, vector index, structured output, telemetry,
the manual adversarial runner) are not complete catalogue features and need
stories when the feature they support is built.
