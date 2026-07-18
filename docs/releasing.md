# Release runbook

1. Update version in `pyproject.toml`, `src/homograph_bel/__init__.py`, and
   `CHANGELOG.md`.
2. For data changes, update the pinned source config, counts, provenance,
   logical hash, resource archive hash, decoder version, and notices.
3. Run `make format`, `make check`, and `make build`.
4. Inspect wheel and sdist contents for generated files, private paths, secrets,
   and missing licenses/data.
5. Install the wheel into a clean environment and run bundled `list`, `detect`,
   `prompt`, and response parsing commands without repository imports.
6. Commit, push `main`, create a signed `vX.Y.Z` tag when possible, and push it.
7. The release workflow reruns checks, builds distributions, smoke-tests the
   wheel, attaches the standalone dictionary, writes `SHA256SUMS`, and creates
   the GitHub release.
8. Verify release assets and CI from a fresh clone.

PyPI publication is intentionally outside the `v0.1.0` release. Add trusted
publishing only after the project name and maintainer policy are confirmed.
