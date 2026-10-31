## Story 1

As a skincare creator, I want customer details removed before they reach the model or get saved, so that I can paste DMs without leaking anyone's private information

- Emails, phone numbers and @handles become `[redacted]` before the model call, in the terminal and in the web chat
- The saved conversation contains only the redacted text
- A message with a personal health detail is refused with a reason and never sent to the model

## Story 2

As a brand owner, I want replies with unapproved product claims stopped, so that I never publish a promise my brand can't support

- A reply saying a product "cures" a condition is stopped with `unsupported_claim`, and nothing of it is saved
- A reply using an approved, in-date claim from brand.json is shown normally
- "Ignore previous instructions" style messages are refused before the model with `unsafe_request`
