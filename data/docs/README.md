# Brand documents (searched by the model)

Sensai searches the `.md` and `.txt` files in this folder, and notices new, edited and removed files by itself. Add your own with `/add <path>` in the terminal chat or with the Documents page of the web UI, or just copy files here. The Serein Studio sheets in this folder are samples: delete or replace them with your own brand documents.

## Document header format

A document may start with a front-matter header (without one, the file name and modified date are used). `product` is only present on product sheets:
- **source** : the related file name without .md
- **type** : document type
- **product** : product ID (P01, P02), matching `tests/fixtures/brand.json`
- **version** : the version date
- **title** : human-readable document title

## Question kinds
- **direct**: the answer is clearly found in one document
- **near-miss**: similar wording exists in another document but the answer belongs to a different product. `source` and `answer` point to that misleading document and text; the expected behavior is to say there is no answer for the product asked about, not to quote them
- **outdated**: the answer exists only in an old document version, not in the current one. `source` and `answer` point to the old version; the expected behavior is not to present it as current
- **unsupported**: no document contains an answer to this question
