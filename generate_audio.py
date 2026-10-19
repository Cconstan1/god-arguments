#!/usr/bin/env python3
"""Generate and cache Google Cloud Text-to-Speech MP3s for argument nodes."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from google.cloud import texttospeech


ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "audio"
CACHE_PATH = AUDIO_DIR / "audio_cache.json"
LANGUAGE_CODE = "en-US"
VOICES = {
    "female": "en-US-Journey-F",
    "male": "en-US-Journey-D",
}
AUDIO_ENCODING = texttospeech.AudioEncoding.MP3
NODE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate cached Google Cloud TTS audio for argument JSON nodes."
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Process one argument tree JSON file (relative paths are based on this script).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate audio even when the cached card text has not changed.",
    )
    return parser.parse_args()


def create_client() -> texttospeech.TextToSpeechClient:
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        return texttospeech.TextToSpeechClient()

    local_credentials = Path.cwd() / "google-tts-key.json"
    if local_credentials.is_file():
        return texttospeech.TextToSpeechClient.from_service_account_file(
            str(local_credentials)
        )

    return texttospeech.TextToSpeechClient()


def load_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {"version": 1, "entries": {}}

    with cache_path.open(encoding="utf-8") as cache_file:
        cache = json.load(cache_file)

    if not isinstance(cache, dict) or not isinstance(cache.get("entries"), dict):
        raise ValueError(f"Invalid audio cache structure: {cache_path}")
    return cache


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def card_text(node: dict[str, Any], source: Path) -> tuple[str, str]:
    node_id = node.get("id")
    title = node.get("title")
    summary = node.get("summary")
    if not isinstance(node_id, str) or not NODE_ID_PATTERN.fullmatch(node_id):
        raise ValueError(f"Invalid or missing node id in {source}: {node_id!r}")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Missing title for node {node_id!r} in {source}")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError(f"Missing summary for node {node_id!r} in {source}")

    text = f"{title.strip()}. {summary.strip()}"
    if len(text.encode("utf-8")) > 5000:
        raise ValueError(f"TTS input exceeds 5000 bytes for node {node_id!r} in {source}")
    return node_id, text


def synthesize(
    client: texttospeech.TextToSpeechClient, text: str, voice_name: str
) -> bytes:
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE, name=voice_name
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=AUDIO_ENCODING
        ),
    )
    if not response.audio_content:
        raise RuntimeError("Google Cloud Text-to-Speech returned empty audio.")
    return response.audio_content


def process_file(
    json_path: Path,
    client: texttospeech.TextToSpeechClient,
    cache: dict[str, Any],
    force: bool,
) -> tuple[int, int]:
    with json_path.open(encoding="utf-8") as json_file:
        argument_data = json.load(json_file)

    if not isinstance(argument_data, dict) or not isinstance(
        argument_data.get("nodes"), list
    ):
        raise ValueError(f"Expected a JSON object with a nodes array: {json_path}")

    root_relative_path = json_path.resolve().relative_to(ROOT).as_posix()
    entries: dict[str, Any] = cache["entries"]
    seen_ids: set[str] = set()
    updated_nodes = 0
    generated_files = 0

    for node in argument_data["nodes"]:
        if not isinstance(node, dict):
            raise ValueError(f"Expected each node to be a JSON object in {json_path}")
        node_id, text = card_text(node, json_path)
        if node_id in seen_ids:
            raise ValueError(f"Duplicate node id {node_id!r} in {json_path}")
        seen_ids.add(node_id)

        audio_urls = {
            gender: f"audio/{node_id}_{gender}.mp3" for gender in VOICES
        }
        cache_key = f"{root_relative_path}#{node_id}"
        cached = entries.get(cache_key)
        voice_cache = cached.get("voices", {}) if isinstance(cached, dict) else {}

        for gender, voice_name in VOICES.items():
            audio_url = audio_urls[gender]
            audio_path = AUDIO_DIR / f"{node_id}_{gender}.mp3"
            cache_input = json.dumps(
                {
                    "text": text,
                    "language_code": LANGUAGE_CODE,
                    "voice": voice_name,
                    "audio_encoding": AUDIO_ENCODING.name,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            digest = hashlib.md5(
                cache_input.encode("utf-8"), usedforsecurity=False
            ).hexdigest()
            cached_voice = voice_cache.get(gender)
            unchanged = (
                isinstance(cached_voice, dict)
                and cached_voice.get("md5") == digest
                and cached_voice.get("audio_url") == audio_url
                and audio_path.is_file()
            )

            if force or not unchanged:
                atomic_write(audio_path, synthesize(client, text, voice_name))
                generated_files += 1
                print(f"Generated {audio_url}")
            else:
                print(f"Cached   {audio_url}")

            voice_cache[gender] = {"md5": digest, "audio_url": audio_url}

        entries[cache_key] = {"voices": voice_cache}
        had_legacy_audio_url = "audio_url" in node
        node.pop("audio_url", None)
        if node.get("audio_urls") != audio_urls:
            node["audio_urls"] = audio_urls
            updated_nodes += 1
        elif had_legacy_audio_url:
            updated_nodes += 1

    if updated_nodes:
        atomic_write(
            json_path,
            (json.dumps(argument_data, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            ),
        )

    return generated_files, updated_nodes


def main() -> None:
    args = parse_args()
    if args.file is None:
        json_files = sorted(ROOT.glob("*_tree.json"))
    else:
        json_path = args.file if args.file.is_absolute() else ROOT / args.file
        json_files = [json_path.resolve()]

    if not json_files:
        raise FileNotFoundError(f"No argument tree JSON files found in {ROOT}")

    for json_path in json_files:
        if not json_path.is_file():
            raise FileNotFoundError(f"Argument JSON file not found: {json_path}")
        try:
            json_path.resolve().relative_to(ROOT)
        except ValueError as error:
            raise ValueError(f"Argument JSON file must be inside {ROOT}: {json_path}") from error

    cache = load_cache(CACHE_PATH)
    cache["version"] = 2
    client = create_client()
    generated_files = 0
    updated_nodes = 0

    for json_path in json_files:
        generated, updated = process_file(json_path, client, cache, args.force)
        generated_files += generated
        updated_nodes += updated

    atomic_write(
        CACHE_PATH,
        (json.dumps(cache, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(
        f"Done: generated {generated_files} MP3 file(s); "
        f"updated audio_urls on {updated_nodes} node(s)."
    )


if __name__ == "__main__":
    main()