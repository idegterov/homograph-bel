"""Benchmark Dictionary v2 scanning independently of bundle load time."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from homograph_bel.inference.benchmark import run_benchmark


def main() -> int:
    """Run the scanner benchmark from the command line."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sentences", type=int, default=100_000)
    arguments = parser.parse_args()
    result = run_benchmark(arguments.bundle, sentences=arguments.sentences)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
