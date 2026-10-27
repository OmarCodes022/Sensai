# Serein Studio fixture documents

## Document header format

Contains 5 parts with source, type, product, version and title. Here's each part in details :
- **source** : the related file name without .md
- **type** : document type
- **product** : production ID (P01, P02)
- **version** : the version date
- **title** : human-readable document title

## question kinds
- **direct**: the answer is clearly found in one document
- **near-miss**: similar wording exists in another document but the answer belongs to a different product
- **outdated**: the answer exists only in an old document version, not in the current one
- **unsupported**: no document contains an answer to this question
