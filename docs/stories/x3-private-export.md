## Story 1

As a skincare creator, I want to save this week's plan and my conversation as files on my computer, so that I can read, print or paste them into my notes outside Sensai

- `/export` (terminal or web chat) writes the conversation and the campaign as JSON and Markdown in exports/
- The campaign Markdown shows the four sections with their status, the calendar as a table and the report figures with their source
- The campaign export is refreshed automatically after each saved change

## Story 2

As a creator, I want exports checked before they are written, so that a saved file never contains a customer's details or a claim I can't make

- Emails, phone numbers and @handles are redacted in the exported copy
- A campaign with an unapproved claim is not exported, the reason is shown, and the previous export is unchanged
- A write error is reported and the chat continues; nothing is uploaded or shared


## Story 3: Send my team a link to the week's calendar

As Nadia, I want to send my team a link to the week's calendar, so that they can see the plan
without installing anything or logging in.

Acceptance criteria:
1. `/share calendar` (or **Share** on the Campaign page) gives a link that opens in any browser on the
   network without login, and the page shows only the calendar.
2. `/unshare` (or **Remove**) makes the link answer 404.
3. `/export` still keeps Markdown and JSON copies of the conversation and the campaign.

## Story 4: Approve exactly what goes public

As Nadia, I want to approve exactly what goes public and be able to take it down, so that a share
never exposes customer messages or drafts I did not choose.

Acceptance criteria:
1. The exact content and link are shown before anything is published, and only a yes publishes.
2. DM replies cannot be shared, a refused claim shares nothing, and nothing outside the section appears.
3. Later edits do not change a shared page without a new confirmation.

Tests: `tests/unit/test_share.py`, `tests/unit/web/test_share_web.py`, `tests/unit/web/test_e2e_week.py`.

Measured on 2026-11-01 with `qwen2.5`: **Share** on the calendar showed the five entries and
`http://<lan>:8767/s/<token>`; after **Share** the link opened the calendar alone; after **Remove** it
answered 404. Testing it found that dates with an hour were redacted as phone numbers (fixed in #159)
and that the link used a VPN address (now the home network address first).
