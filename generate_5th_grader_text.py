#!/usr/bin/env python3
"""Generate fifth-grade summaries for argument tree and index JSON files."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from google import genai


ROOT = Path(__file__).resolve().parent
MODEL = "gemini-2.5-flash"
PROMPT_TEMPLATE = (
    "Rewrite this philosophical summary for a 5th grader using "
    "easy-to-understand words, simple phrasing, and a clear real-world analogy: "
    "{summary}"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate fifth-grade summaries with the Google Gemini API."
    )
    parser.add_argument(
        "--file",
        type=Path,
        nargs="+",
        help=(
            "Process one or more JSON files (relative paths are based on this "
            "script). By default, process *_tree.json and arguments_index.json."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate summaries that already have a summary_5th_grader value.",
    )
    return parser.parse_args()


def create_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY to use the Gemini API."
        )
    return genai.Client(api_key=api_key)


def collection_key_for(path: Path) -> str:
    return "arguments" if path.name == "arguments_index.json" else "nodes"


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def generate_summary(client: genai.Client, summary: str, source: Path) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=PROMPT_TEMPLATE.format(summary=summary),
    )
    generated = response.text
    if not isinstance(generated, str) or not generated.strip():
        raise RuntimeError(f"Gemini returned an empty summary for {source}.")
    return generated.strip()


def process_file(
    path: Path, client: genai.Client, force: bool
) -> tuple[int, int]:
    with path.open(encoding="utf-8") as json_file:
        data = json.load(json_file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")

    collection_key = collection_key_for(path)
    entries = data.get(collection_key)
    if not isinstance(entries, list):
        raise ValueError(
            f"Expected a {collection_key!r} array in {path}"
        )

    generated_count = 0
    skipped_count = 0
    updated = False

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Expected each {collection_key} entry to be an object in {path}")

        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"Missing or empty summary in {path}: {entry.get('id')!r}")

        existing = entry.get("summary_5th_grader")
        if not force and isinstance(existing, str) and existing.strip():
            skipped_count += 1
            continue

        entry["summary_5th_grader"] = generate_summary(client, summary.strip(), path)
        generated_count += 1
        updated = True
        print(f"Generated fifth-grade summary for {entry.get('id', path.name)}")

    if updated:
        atomic_write_json(path, data)

    return generated_count, skipped_count


def main() -> None:
    args = parse_args()
    if args.file:
        json_files = [
            (path if path.is_absolute() else ROOT / path).resolve()
            for path in args.file
        ]
    else:
        json_files = sorted(ROOT.glob("*_tree.json"))
        index_path = ROOT / "arguments_index.json"
        if index_path.is_file():
            json_files.append(index_path)

    if not json_files:
        raise FileNotFoundError(f"No supported JSON files found in {ROOT}")

    client = create_client()
    total_generated = 0
    total_skipped = 0
    for json_path in json_files:
        if not json_path.is_file():
            raise FileNotFoundError(f"JSON file not found: {json_path}")
        generated, skipped = process_file(json_path, client, args.force)
        total_generated += generated
        total_skipped += skipped
        print(f"{json_path.name}: {generated} generated, {skipped} skipped")

    print(
        f"Done: {total_generated} summaries generated, "
        f"{total_skipped} existing summaries skipped."
    )


if __name__ == "__main__":
    main()
