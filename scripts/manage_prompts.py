"""Create, list and re-label the Langfuse text prompt used by the lab (docs/PROMPT_VERSIONING.md).

Usage:
    python scripts/manage_prompts.py seed            # v1 (baseline, production) + v2 (candidate)
    python scripts/manage_prompts.py list
    python scripts/manage_prompts.py promote 2       # move `production` to version 2
    python scripts/manage_prompts.py promote 1       # rollback `production` to version 1
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from langfuse import get_client  # noqa: E402

NAME = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")

PROMPT_V1 = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"
# v2 = one small change: ask for a concise answer. The three variables are unchanged.
PROMPT_V2 = PROMPT_V1 + "\nAnswer concisely in at most three sentences."


def seed(client) -> None:
    v1 = client.create_prompt(name=NAME, prompt=PROMPT_V1, labels=["baseline", "production"], type="text")
    v2 = client.create_prompt(name=NAME, prompt=PROMPT_V2, labels=["candidate"], type="text")
    print(f"created {NAME} v{v1.version} labels={v1.labels}")
    print(f"created {NAME} v{v2.version} labels={v2.labels}")


def show(client) -> None:
    meta = client.api.prompts.list(name=NAME)
    for item in meta.data:
        print(f"{item.name}: versions={item.versions} labels={item.labels}")
    for label in ("baseline", "candidate", "production"):
        try:
            p = client.get_prompt(NAME, label=label, type="text", cache_ttl_seconds=0)
            print(f"  label {label:<10} -> v{p.version}")
        except Exception as exc:  # label may not exist yet
            print(f"  label {label:<10} -> {type(exc).__name__}")


def promote(client, version: int) -> None:
    client.update_prompt(name=NAME, version=version, new_labels=["production"])
    print(f"label production now points to {NAME} v{version}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"seed", "list", "promote"}:
        sys.exit(__doc__)
    client = get_client()
    cmd = sys.argv[1]
    if cmd == "seed":
        seed(client)
    elif cmd == "promote":
        promote(client, int(sys.argv[2]))
    show(client)
    client.flush()


if __name__ == "__main__":
    main()
