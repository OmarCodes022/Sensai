## Story 1

As a skincare creator, I want to rewrite an earlier request and continue from there, so that I can try another direction for a caption without losing the version I already have

- `/edit N <new text>` (terminal or web chat) continues the conversation from message N with the new text, and the reply only knows the messages before N
- The original conversation is still listed and opens unchanged
- The branch is saved as its own session, titled like the original plus "(branch)"

## Story 2

As a creator, I want to stop a reply that is going in the wrong direction and redirect it right away, so that I don't wait for a long answer I won't use

- Ctrl+C or Esc in the terminal, or Stop in the web chat, stops the reply mid-stream
- The stopped reply is not kept in the conversation or the saved session, and an interrupted `/edit` creates no branch
- My next message is answered with the earlier completed exchanges as context
