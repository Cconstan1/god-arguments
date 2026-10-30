#!/usr/bin/env python3
"""Generate fifth-grade summaries for argument tree and index JSON files."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
MODEL = "gemini-2.0-flash"
FALLBACK_MODELS = ("gemini-2.0-flash-lite", "gemini-1.5-pro")
API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
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


def load_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key and api_key.strip():
        return api_key.strip()

    credentials_path = ROOT / "google-tts-key.json"
    if credentials_path.is_file():
        with credentials_path.open(encoding="utf-8") as credentials_file:
            credentials = json.load(credentials_file)
        if isinstance(credentials, dict):
            for key_name in (
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "api_key",
                "apikey",
                "key",
            ):
                value = credentials.get(key_name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        raise ValueError(
            f"{credentials_path} does not contain an API key. "
            "Set GEMINI_API_KEY or GOOGLE_API_KEY, or provide an API key in "
            "that JSON file; service-account credentials are not API keys."
        )

    raise RuntimeError(
        "Set GEMINI_API_KEY or GOOGLE_API_KEY, or provide an API key in "
        f"{credentials_path}."
    )


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


def generate_summary(api_key: str, summary: str, source: Path) -> str:
    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT_TEMPLATE.format(summary=summary)},
                ],
            },
        ],
    }
    response_data: Any = None
    for model in (MODEL, *FALLBACK_MODELS):
        request_url = API_URL_TEMPLATE.format(model=model)
        request = Request(
            request_url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as error:
            print(f"Gemini API request failed: {request.full_url}")
            error_body = error.read().decode("utf-8", errors="replace")
            if error.code == 404 and model != FALLBACK_MODELS[-1]:
                print(f"Gemini model {model} returned HTTP 404; trying next model.")
                continue
            raise RuntimeError(
                f"Gemini API returned HTTP {error.code} for {source} "
                f"using {model}: {error_body}"
            ) from error

    candidates = response_data.get("candidates")
    generated = None
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content")
        if isinstance(content, dict):
            parts = content.get("parts")
            if isinstance(parts, list):
                generated = "".join(
                    part["text"]
                    for part in parts
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
    if not isinstance(generated, str) or not generated.strip():
        raise RuntimeError(f"Gemini returned an empty summary for {source}.")
    return generated.strip()


def process_file(
    path: Path, api_key: str, force: bool
) -> tuple[int, int]:
    with path.open(encoding="utf-8") as json_file:
        data = json.load(json_file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")

    collection_key = collection_key_for(path)
    entries = data.get(collection_key)
    if not isinstance(entries, list):
        raise ValueError(f"Expected a {collection_key!r} array in {path}")

    generated_count = 0
    skipped_count = 0
    updated = False

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Expected each {collection_key} entry to be an object in {path}"
            )

        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(
                f"Missing or empty summary in {path}: {entry.get('id')!r}"
            )

        existing = entry.get("summary_5th_grader")
        if not force and isinstance(existing, str) and existing.strip():
            skipped_count += 1
            continue

        entry["summary_5th_grader"] = generate_summary(api_key, summary.strip(), path)
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

    if not json_files:
        raise FileNotFoundError(f"No supported JSON files found in {ROOT}")

    api_key = load_api_key()
    total_generated = 0
    total_skipped = 0
    for json_path in json_files:
        if not json_path.is_file():
            raise FileNotFoundError(f"JSON file not found: {json_path}")
        generated, skipped = process_file(json_path, api_key, args.force)
        total_generated += generated
        total_skipped += skipped
        print(f"{json_path.name}: {generated} generated, {skipped} skipped")

    print(
        f"Done: {total_generated} summaries generated, "
        f"{total_skipped} existing summaries skipped."
    )


if __name__ == "__main__":
    main()
