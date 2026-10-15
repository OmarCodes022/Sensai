# Epitech mirror and evidence

`OmarCodes022/Sensai` is the source repository. The Epitech destination is
`EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1`.

- **Mirror:** `.github/workflows/mirror.yml` runs on a push to any branch.
  It checks out the repository with full history and uses the Actions
  secret `EPITECH_PAT` to push to Epitech over HTTPS. Its two commands are
  `git push epitech --all --force` and `git push epitech --tags --force`:
  they force-update local branches and tags, without deleting destination
  refs. `--all` pushes local branches, not every remote-tracking branch.
- **Evidence:** `.github/workflows/sync-merge-evidence.yml` independently
  handles personal `main` pushes when `SENSAI_EVIDENCE_SYNC_ENABLED=true`.
  See [merge-evidence-sync.md](merge-evidence-sync.md) for its credentials
  and activation rules.

These workflows run independently: mirroring does not wait for evidence
sync. A failed mirror run leaves the repositories different;
inspect GitHub Actions and retry after resolving the failure. Forced pushes
can replace divergent destination history. No application release or
deployment is performed.
