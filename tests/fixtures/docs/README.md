# Serein Studio fixture documents

## Document header format

Each document starts with a front-matter header. `product` is only present on product sheets:
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
