## Story 1

As a skincare creator, I want Sensai to ask which product I mean when I don't say it, so that I don't get a caption for the wrong product

- When the product is missing, Sensai shows a choice list (terminal) or a form card (web chat) instead of guessing, never raw JSON
- After I choose an option, the reply continues with that product
- The question and my answer remain in the saved conversation

## Story 2

As a creator, I want to correct a typo or skip a question, so that one mistake doesn't derail the conversation

- An invalid choice shows an error and asks again
- Ctrl+C in the terminal, or Skip in the web chat, skips the question, and I can keep chatting
- A skipped question doesn't break the conversation: the model is told I skipped it
