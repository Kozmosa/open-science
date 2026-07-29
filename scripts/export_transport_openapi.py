"""Export the deterministic OpenScience HTTP transport contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ainrf.api.transport_schema import build_transport_openapi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.dumps(
        build_transport_openapi(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(f"{payload}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
