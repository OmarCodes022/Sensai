## Story 1

As a skincare creator, I want Sensai to answer from my product sheets, so that captions and replies use my real approved product facts instead of invented claims

- A question covered by the documents gets a correct answer from the product sheet
- After I update a document and run /reindex, the next answer uses the new version
- Each answer shows which documents it came from

## Story 2

As a creator, I want Sensai to say when my documents don't cover a question, so that it never invents a product claim I could accidentally publish

- An uncovered question gets a clear "not in the documents" answer
- /docs <text> shows what Sensai would find for a question, without asking the model
- If the embedding model is missing, Sensai tells me how to fix it and chat still works