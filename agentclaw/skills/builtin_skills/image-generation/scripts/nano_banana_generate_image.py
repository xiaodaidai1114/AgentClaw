#!/usr/bin/env python3
"""Generate or edit images with Nano Banana image models through Gemini API."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
import sys
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


NANO_BANANA_MODELS = {
    "nano-banana-2": "gemini-3.1-flash-image-preview",
    "nano-banana-pro": "gemini-3-pro-image-preview",
    "nano-banana": "gemini-2.5-flash-image",
}
DEFAULT_OUTPUT_DIR = "generated_images"
PROJECT_DIR = Path(__file__).resolve().parents[5]


def _load_project_env() -> None:
    try:
        from dotenv import dotenv_values, find_dotenv, load_dotenv
    except ImportError:
        return

    candidates: list[Path] = []
    if os.getenv("AGENTCLAW_PROJECT_DIR"):
        candidates.append(Path(os.environ["AGENTCLAW_PROJECT_DIR"]).expanduser() / ".env")

    found = find_dotenv(usecwd=True)
    if found:
        candidates.append(Path(found))
    candidates.extend([Path.cwd() / ".env", PROJECT_DIR / ".env"])

    seen: set[Path] = set()
    for candidate in candidates:
        env_file = candidate.expanduser().resolve()
        if env_file in seen or not env_file.is_file():
            continue
        seen.add(env_file)
        load_dotenv(env_file, override=False)
        for key, value in dotenv_values(env_file).items():
            if value is not None and not os.getenv(key):
                os.environ[key] = value


def resolve_model_id(banana: str) -> str:
    try:
        return NANO_BANANA_MODELS[banana]
    except KeyError as exc:
        choices = ", ".join(sorted(NANO_BANANA_MODELS))
        raise SystemExit(f"Unknown Nano Banana variant: {banana}. Choose one of: {choices}.") from exc


def _api_key() -> str:
    _load_project_env()
    api_key = os.getenv("GOOGLE_IMAGE_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_IMAGE_KEY is required for Nano Banana image generation.")
    return api_key


def _mime_type(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "image/png"


def _encode_inline_data(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Input image file not found: {path}")
    return {
        "inline_data": {
            "mime_type": _mime_type(path),
            "data": base64.b64encode(path.read_bytes()).decode("utf-8"),
        }
    }


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": args.prompt}]
    parts.extend(_encode_inline_data(Path(path)) for path in args.input_image)

    generation_config: dict[str, Any] = {
        "responseModalities": ["TEXT", "IMAGE"] if args.include_text else ["IMAGE"],
    }
    image_config: dict[str, Any] = {}
    if args.aspect_ratio:
        image_config["aspectRatio"] = args.aspect_ratio
    if args.image_size:
        image_config["imageSize"] = args.image_size
    if image_config:
        generation_config["imageConfig"] = image_config
    if args.thinking_level or args.include_thoughts:
        thinking_config: dict[str, Any] = {}
        if args.thinking_level:
            thinking_config["thinkingLevel"] = args.thinking_level
        if args.include_thoughts:
            thinking_config["includeThoughts"] = True
        generation_config["thinkingConfig"] = thinking_config

    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }

    if args.google_search:
        google_search: dict[str, Any] = {}
        if args.image_search:
            google_search["searchTypes"] = {"webSearch": {}, "imageSearch": {}}
        payload["tools"] = [{"google_search": google_search}]

    return payload


def _request_json(model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": _api_key(),
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Nano Banana API request failed with HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise SystemExit(f"Nano Banana API request failed: {exc}") from exc


def _suffix_from_mime(mime_type: str) -> str:
    if mime_type == "image/jpeg":
        return "jpg"
    if mime_type == "image/webp":
        return "webp"
    return "png"


def _write_image(image_base64: str, mime_type: str, output_dir: Path, output_prefix: str, index: int) -> str:
    output_path = output_dir / f"{output_prefix}_{index}.{_suffix_from_mime(mime_type)}"
    output_path.write_bytes(base64.b64decode(image_base64))
    return str(output_path)


def _extract_outputs(response: dict[str, Any], output_dir: Path, output_prefix: str) -> tuple[list[str], list[str], dict[str, Any]]:
    output_paths: list[str] = []
    text_parts: list[str] = []
    grounding_metadata: dict[str, Any] = {}

    for candidate in response.get("candidates", []) or []:
        if candidate.get("groundingMetadata"):
            grounding_metadata = candidate["groundingMetadata"]
        for part in candidate.get("content", {}).get("parts", []) or []:
            if part.get("thought"):
                continue
            text = part.get("text")
            if text:
                text_parts.append(str(text))
            inline_data = part.get("inline_data") or part.get("inlineData")
            if not inline_data:
                continue
            image_base64 = inline_data.get("data")
            mime_type = inline_data.get("mime_type") or inline_data.get("mimeType") or "image/png"
            if image_base64:
                output_paths.append(
                    _write_image(
                        str(image_base64),
                        str(mime_type),
                        output_dir,
                        output_prefix,
                        len(output_paths) + 1,
                    )
                )

    return output_paths, text_parts, grounding_metadata


def run(args: argparse.Namespace) -> dict[str, Any]:
    model_id = resolve_model_id(args.banana)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = _build_payload(args)
    response = _request_json(model_id, payload)
    output_paths, text_parts, grounding_metadata = _extract_outputs(response, output_dir, args.output_prefix)

    operation = "edit" if args.input_image else "generate"
    if args.google_search:
        operation = "grounded_" + operation

    return {
        "provider": "nano-banana",
        "banana": args.banana,
        "model": model_id,
        "operation": operation,
        "prompt": args.prompt,
        "output_dir": str(output_dir),
        "absolute_output_dir": str(output_dir.resolve()),
        "output_paths": output_paths,
        "response_id": response.get("responseId"),
        "revised_prompts": [],
        "metadata": {
            "image_count": len(output_paths),
            "input_image_count": len(args.input_image),
            "aspect_ratio": args.aspect_ratio,
            "image_size": args.image_size,
            "text": text_parts,
            "grounding_metadata": grounding_metadata,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit images with Nano Banana image models.")
    parser.add_argument("--prompt", required=True, help="Text prompt for image generation or editing.")
    parser.add_argument(
        "--banana",
        default="nano-banana-2",
        choices=sorted(NANO_BANANA_MODELS),
        help="Nano Banana variant. Defaults to nano-banana-2.",
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for generated image files.")
    parser.add_argument("--output-prefix", default="image", help="Filename prefix for generated image files.")
    parser.add_argument("--input-image", action="append", default=[], help="Reference/source image path. Repeat for multiple images.")
    parser.add_argument("--aspect-ratio", default=None, help="Aspect ratio such as 1:1, 16:9, 3:2, 1:4, or 8:1.")
    parser.add_argument("--image-size", default=None, help="Image size such as 512, 1K, 2K, or 4K when supported.")
    parser.add_argument("--include-text", action="store_true", help="Allow the response to include text alongside image output.")
    parser.add_argument("--google-search", action="store_true", help="Use Google Search grounding for real-time visual facts.")
    parser.add_argument("--image-search", action="store_true", help="Enable Google image search grounding with web search.")
    parser.add_argument("--thinking-level", choices=["minimal", "high"], default=None, help="Nano Banana 2 thinking level when supported.")
    parser.add_argument("--include-thoughts", action="store_true", help="Ask the API to return thought parts when supported.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    if args.image_search and not args.google_search:
        raise SystemExit("--image-search requires --google-search.")
    if args.include_thoughts and not args.thinking_level:
        args.thinking_level = "high"

    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
