# Security policy

Security fixes are supported for the latest release.

Please report vulnerabilities through GitHub's private security advisory flow:
**Security → Advisories → New draft security advisory**. Do not open a public
issue for an undisclosed vulnerability.

The package performs no runtime network access. Bundled data is checksum-verified
before extraction, archive members are restricted to an exact allow-list, and
LLM responses must pass the closed-choice parser. Applications should still
treat input text, custom dictionary bundles, and model responses as untrusted.
