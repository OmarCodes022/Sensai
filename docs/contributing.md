# Contributing

## Branches, commits and pull requests

- Make one branch per change, created from an up-to-date `main`, for example
  `feat/cli-history` or `docs/mkdocs-site`.
- Keep commits small and atomic, with
  [Conventional Commits](https://www.conventionalcommits.org/) messages such as
  `feat(cli): add /history` or `docs: describe the sandbox limits`.
- Open a pull request to `main`. Merging needs one approving review and a
  passing `Unit tests` check.
- Run the unit tests before pushing; see [Getting started](getting-started.md).

## Workflows

| Workflow | File | Runs on | Does |
| --- | --- | --- | --- |
| Tests | `.github/workflows/tests.yml` | Push and pull request to `main` | Runs the offline unit tests (job `Unit tests`) |
| Documentation | `.github/workflows/docs.yml` | Push and pull request to `main`, manual run | Builds this site with `mkdocs build --strict`; deploys it from `main` only |
| Epitech Mirror | `.github/workflows/mirror.yml` | Push to any branch | Force-pushes branches and tags to the Epitech repository |

Details: [documentation site](operations/documentation.md) and
[Epitech mirror](operations/epitech-mirror.md).

## Adding a documentation page

1. Create the Markdown file under `docs/`, in the folder that fits
   (`architecture/`, `product/`, `operations/`...).
2. Add it to the `nav` section of `mkdocs.yml`, and to the list in
   `docs/README.md`. A page missing from `nav` fails the build.
3. Link to other pages with relative paths to their `.md` files. Link to files
   outside `docs/` with their full GitHub URL.
4. Preview it, then run the strict build; both are described in
   [Documentation site](operations/documentation.md#preview-locally).
