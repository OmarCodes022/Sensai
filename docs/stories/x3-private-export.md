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
