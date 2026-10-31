## Story 1

As a creator, I want Sensai's edits to follow a fixed format, so that they can be saved and reused without me fixing them by hand

- Every edit is JSON matching the section's schema, forced by Ollama's format option
- Wrong fields, types or missing values are rejected with a clear message
- Every saved item has all its required fields

## Story 2

As a brand owner, I want structured items checked against my brand data, so that drafts never point to missing posts or unapproved claims

- A calendar entry with an unknown post id, or a date outside the week, is rejected
- A post with an unapproved or expired claim id is rejected
- Report figures come from the data, never from the model
