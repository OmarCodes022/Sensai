## Story 1

As a skincare creator, I want Sensai to prepare my weekly post ideas on its own, so that fresh ideas are waiting for me each week without asking

- A task in the file runs at its interval without me typing anything (terminal command, or in the background of the web interface)
- Each run saves a dated draft in drafts/, which I can open on the Schedule page
- Nothing is published or sent; I decide what to use

## Story 2

As a creator, I want scheduled runs to survive problems, so that one failure doesn't stop the next drafts

- A failed run prints (or shows) the error and saves no draft
- The scheduler retries at the next interval
- An invalid tasks file is refused before anything runs
