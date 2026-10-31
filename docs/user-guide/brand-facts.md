# Brand facts (memory)

Sensai keeps a small fact sheet about the brand in its SQLite database: prices, launch
dates, product details. The model adds, corrects and deletes facts itself when you tell it
something, so you don't repeat it every session and it never keeps an outdated price.

```text
> Hydra Glow Serum now costs 32 €.
Using tool: save_fact({"id": "hydra-glow-serum.price", "text": "Costs 32 €"})
Noted, the serum is now 32 €.
Memory: added hydra-glow-serum.price
> /facts
hydra-glow-serum.price  Costs 32 €  (chat 2026-10-31)
```

## How it works

- Each fact has an id that names the product and the topic, such as
  `hydra-glow-serum.price`, a one-line text and a source (`chat <date>`, or `edited <date>`
  when you wrote it yourself).
- The model calls `save_fact` (add or correct, reusing the id) and `delete_fact` (no longer
  true). A tool call only queues the change: it is written when the reply completes, and
  dropped if you interrupt it (Ctrl+C, Esc, Stop) or it fails. Each change prints a
  `Memory: …` line.
- The facts are added to the model's instructions in every session, also after `/persona`.
- Facts are kept separately for each creator (`--creator`).

## In the terminal

`/facts` lists the facts with their source; `/tools` lists `save_fact` and `delete_fact`.

## In the web interface

A **Memory:** chip appears under the reply that changed a fact. The **Brand facts** page (or
`/facts` in the chat) lists the facts, and lets you add, correct or delete one yourself. Its
second tab shows the approved claims register read from `brand.json` in the data folder,
with each claim's validity.

## Limits

Small models sometimes forget to call the tool, or write a fact you did not mean to save:
check the Memory line or the Brand facts page. Facts are plain sentences, not checked against
the claims register.
