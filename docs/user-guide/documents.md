# Document search

Sensai can answer from your own brand documents (product sheets, FAQ, brand voice)
instead of inventing facts. The model searches them by itself whenever a question
needs one, and cites the documents it used.

## Set up once

```bash
ollama pull nomic-embed-text
```

That is the embedding model: it turns each paragraph into numbers so a search can find
the closest ones. Without it, search is switched off and everything else keeps working.

## Where documents live

In `data/docs/` at the repository root. The folder ships with fictional Serein Studio
sample sheets so search works out of the box; replace them with your own. Your files
stay out of git.

- **Types:** `.md` and `.txt`, up to 2 MB each and 20 MB in all.
- **Header (optional):** a block between two `---` lines on the first line of the file:

  ```text
  ---
  source: hydra-glow-serum
  type: product-sheet
  product: P01
  version: 2026-09-01
  title: Hydra Glow Serum
  ---
  ```

  Without a header the file name is the source and the modified date is the version.
  `product` and `version` are what lets Sensai mark an older sheet as OUTDATED when a
  newer one for the same product exists.
- `README.md` is never indexed.

## Adding documents

In the terminal chat, from anywhere on your computer:

| Command | What it does |
| --- | --- |
| `/add <file or folder> [...]` | Copies the file (or the `.md`/`.txt` files of a folder) into `data/docs/` and indexes it. Quote paths with spaces, or paste them as they are. A file with the same name is replaced. |
| `/remove <name>` | Deletes a document from `data/docs/`. |
| `/docs` | Lists the documents and the search status. |
| `/docs <text>` | Shows what a search for that text finds, without asking the model. |
| `/reindex` | Forces a full rebuild (normally never needed). |

You can also copy files into `data/docs/` yourself. New, edited and removed files are
noticed before each question and indexed in the background; a one-line note appears at
the next prompt ("Document search: 2 documents indexed."). Until a file is ready,
searches use what is already indexed.

## How it behaves

- The search instructions are added to the model's prompt only while there are
  documents, and removed when the last one goes.
- Embeddings are cached in the session database, so a restart does not re-embed
  unchanged text, and editing a file only re-embeds the paragraphs that changed.
- Another folder: `--docs <folder>` or `SENSAI_DOCS`. `SENSAI_DOCS=` (empty) switches
  search off. The embedding model is `SENSAI_EMBED_MODEL`.
- The Python sandbox never sees these files (only the top-level files of `data/`).

## Limits

Documents are split into paragraphs and the three closest are returned per search, so
very short or very long paragraphs search less well. A search needs Ollama running for
the question's embedding. Search finds text, not meaning beyond what the embedding
model captures: always check an important claim against the cited source.
