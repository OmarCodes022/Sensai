## Story 1

As a skincare creator, I want Sensai to remember the product facts I mention and update them when they change, so that I don't repeat them every session and it never uses an outdated price or date

- Telling it a new fact shows a `Memory: added …` line, and the fact appears in `/facts` and on the Brand facts page with its source
- A correction updates the existing fact instead of adding a second one
- A new session uses the stored fact

## Story 2

As a creator, I want Sensai's memory changes to be visible and safe, so that a bad or interrupted reply can't corrupt my fact sheet

- Each change shows a `Memory:` line in the terminal or a Memory chip in the web chat
- An invalid tool call or an interrupted reply changes nothing
- Another creator's facts are never shown or changed, and I can correct or delete any fact myself on the Brand facts page
