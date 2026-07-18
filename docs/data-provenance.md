# Data provenance and contract

The checked-in archive is a redistribution-safe derived subset of Belarus
GrammarDB `RELEASE-202601`. Pinning details and checksums are recorded in
`configs/dictionary/grammar-db-v2.toml` and `NOTICE.md`.

The archive contains exactly:

```text
dictionary/manifest.json
dictionary/homographs.jsonl
dictionary/candidates.jsonl
dictionary/analyses.jsonl
```

`manifest.json` identifies schema `dictionary-v2`, upstream release, the three
table checksums, and a logical dictionary hash. Tables are newline-delimited
UTF-8 JSON and link through stable `homograph_id`, `variant_id`, and
`analysis_id` values. Analyses retain source paradigm, variant, and form
coordinates plus dictionary attribution.

The package archive is independently SHA-256 checked before extraction. Tar
members outside the exact allow-list, absolute/traversal paths, links, special
files, missing files, and unexpected files are rejected. The loaded index then
validates table hashes, schema, links, IDs, source releases, and logical hash.

This layered verification detects packaging corruption; it is not a digital
signature. Release assets publish `SHA256SUMS` for transport verification.
