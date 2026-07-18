# Contributing

Issues and focused pull requests are welcome. Before starting a large data or
contract change, open an issue so identifiers, provenance, and compatibility can
be discussed first.

## Local checks

Install Python 3.12 or 3.13 and uv, then run:

```bash
make setup
make check
```

Write a failing test before production behavior and keep the implementation
small. Public contract changes require documentation and a changelog entry.
Never commit source corpora, credentials, model checkpoints, generated caches,
or data whose redistribution terms are unclear.

## Data changes

A dictionary update must pin the upstream release, archive checksum, source
commit, orthography, XML member list, derived logical hash, archive hash, record
counts, license, and modifications. Stable IDs and source coordinates must be
preserved or a migration must be documented.

By contributing code, you agree that it may be distributed under
GPL-3.0-or-later. Data contributions must be compatible with CC BY-SA 4.0 and
include provenance.
