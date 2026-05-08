#!/usr/bin/env python3
"""Generate or edit images with Volcengine Ark Seedream image models."""

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
from urllib.parse import urlparse


ARK_IMAGE_GENERATION_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
SEEDREAM_MODELS = {
    "seedream-5": "doubao-seedream-5-0-260128"
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


def resolve_model_id(args: argparse.Namespace) -> str:
    if args.model_id:
        return args.model_id
    try:
        return SEEDREAM_MODELS[args.seedream]
    except KeyError as exc:
        choices = ", ".join(sorted(SEEDREAM_MODELS))
        raise SystemExit(f"Unknown Seedream variant: {args.seedream}. Choose one of: {choices}.") from exc


def resolve_operation(args: argparse.Namespace) -> str:
    prefix = "image_to_image" if args.input_image else "text_to_image"
    if args.sequential_image_generation == "auto":
        return prefix + "_group"
    return prefix


def _api_key() -> str:
    _load_project_env()
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise SystemExit("ARK_API_KEY is required for Seedream image generation.")
    return api_key


def _mime_type(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "image/png"


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _is_data_url(value: str) -> bool:
    return value.startswith("data:image/") and ";base64," in value


def _encode_image_input(value: str) -> str:
    if _is_url(value) or _is_data_url(value):
        return value
    path = Path(value)
    if not path.is_file():
        raise SystemExit(f"Input image file not found: {value}")
    image_base64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{_mime_type(path)};base64,{image_base64}"


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": resolve_model_id(args),
        "prompt": args.prompt,
        "sequential_image_generation": args.sequential_image_generation,
        "response_format": args.response_format,
        "size": args.size,
        "stream": args.stream,
        "watermark": args.watermark,
    }

    if args.input_image:
        images = [_encode_image_input(value) for value in args.input_image]
        payload["image"] = images[0] if len(images) == 1 else images

    if args.sequential_image_generation == "auto":
        payload["sequential_image_generation_options"] = {"max_images": args.max_images}

    if args.output_format:
        payload["output_format"] = args.output_format
    if args.web_search:
        payload["tools"] = [{"type": "web_search"}]
    if args.optimize_prompt_mode:
        payload["optimize_prompt_options"] = {"mode": args.optimize_prompt_mode}
    if args.seed is not None:
        payload["seed"] = args.seed
    if args.guidance_scale is not None:
        payload["guidance_scale"] = args.guidance_scale

    return payload


def _post_json(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        ARK_IMAGE_GENERATION_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Seedream API request failed with HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise SystemExit(f"Seedream API request failed: {exc}") from exc


def _post_stream(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        ARK_IMAGE_GENERATION_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
    )
    events: list[dict[str, Any]] = []
    try:
        with urllib_request.urlopen(req, timeout=300) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line.removeprefix("data:").strip()
                if line == "[DONE]":
                    break
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Seedream API stream failed with HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise SystemExit(f"Seedream API stream failed: {exc}") from exc
    return events


def _suffix_from_content_type(content_type: str | None, fallback_url: str | None = None) -> str:
    if content_type:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == "image/png":
            return "png"
        if media_type == "image/webp":
            return "webp"
        if media_type in {"image/jpeg", "image/jpg"}:
            return "jpg"
    if fallback_url:
        suffix = Path(urlparse(fallback_url).path).suffix.lower().lstrip(".")
        if suffix in {"png", "jpg", "jpeg", "webp"}:
            return "jpg" if suffix == "jpeg" else suffix
    return "jpg"


def _write_b64_image(image_base64: str, output_dir: Path, output_prefix: str, index: int, suffix: str) -> str:
    output_path = output_dir / f"{output_prefix}_{index}.{suffix}"
    output_path.write_bytes(base64.b64decode(image_base64))
    return str(output_path)


def _download_image(url: str, output_dir: Path, output_prefix: str, index: int) -> str:
    req = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(req, timeout=180) as response:
            content = response.read()
            suffix = _suffix_from_content_type(response.headers.get("Content-Type"), url)
    except HTTPError as exc:
        raise SystemExit(f"Failed to download Seedream image URL with HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        raise SystemExit(f"Failed to download Seedream image URL: {url}: {exc}") from exc

    output_path = output_dir / f"{output_prefix}_{index}.{suffix}"
    output_path.write_bytes(content)
    return str(output_path)


def _iter_data_items(response_or_event: dict[str, Any]) -> list[dict[str, Any]]:
    data = response_or_event.get("data") or []
    if isinstance(data, dict):
        return [data]
    return [item for item in data if isinstance(item, dict)]


def _raise_request_error(response_or_event: dict[str, Any]) -> None:
    error = response_or_event.get("error")
    if not error:
        return
    if isinstance(error, dict):
        code = error.get("code", "unknown_error")
        message = error.get("message", "")
        raise SystemExit(f"Seedream API request failed: {code}: {message}")
    raise SystemExit(f"Seedream API request failed: {error}")


def _collect_outputs(responses: list[dict[str, Any]], args: argparse.Namespace, output_dir: Path) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    output_paths: list[str] = []
    item_errors: list[dict[str, Any]] = []
    urls: list[str] = []

    for response in responses:
        _raise_request_error(response)
        for item in _iter_data_items(response):
            error = item.get("error")
            if error:
                item_errors.append(error)
                continue
            image_base64 = item.get("b64_json")
            url = item.get("url")
            if image_base64:
                suffix = args.output_format or "jpg"
                output_paths.append(
                    _write_b64_image(
                        str(image_base64),
                        output_dir,
                        args.output_prefix,
                        len(output_paths) + 1,
                        suffix,
                    )
                )
            elif url:
                urls.append(str(url))
                if args.download:
                    output_paths.append(
                        _download_image(
                            str(url),
                            output_dir,
                            args.output_prefix,
                            len(output_paths) + 1,
                        )
                    )

    return output_paths, item_errors, urls


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = _build_payload(args)
    responses = _post_stream(payload) if args.stream else [_post_json(payload)]
    output_paths, item_errors, urls = _collect_outputs(responses, args, output_dir)
    final_response = responses[-1] if responses else {}

    return {
        "provider": "seedream",
        "seedream": args.seedream,
        "model": payload["model"],
        "operation": resolve_operation(args),
        "prompt": args.prompt,
        "output_dir": str(output_dir),
        "absolute_output_dir": str(output_dir.resolve()),
        "output_paths": output_paths,
        "response_id": final_response.get("id"),
        "revised_prompts": [],
        "metadata": {
            "image_count": len(output_paths),
            "input_image_count": len(args.input_image),
            "sequential_image_generation": args.sequential_image_generation,
            "max_images": args.max_images if args.sequential_image_generation == "auto" else None,
            "size": args.size,
            "stream": args.stream,
            "watermark": args.watermark,
            "response_format": args.response_format,
            "urls": urls,
            "item_errors": item_errors,
            "usage": final_response.get("usage"),
            "tools": final_response.get("tools"),
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit images with Volcengine Ark Seedream.")
    parser.add_argument("--prompt", required=True, help="Text prompt for image generation or image editing.")
    parser.add_argument(
        "--seedream",
        default="seedream-5",
        choices=sorted(SEEDREAM_MODELS),
        help="Seedream variant. Defaults to seedream-5.",
    )
    parser.add_argument("--model-id", default=None, help="Advanced override: Ark model ID or endpoint ID.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for generated image files.")
    parser.add_argument("--output-prefix", default="image", help="Filename prefix for generated image files.")
    parser.add_argument("--input-image", action="append", default=[], help="Reference image URL, data URL, or local path. Repeat for multiple images.")
    parser.add_argument("--size", default="2K", help="Output size such as 2K, 3K, 4K, or pixel size like 2048x2048.")
    parser.add_argument(
        "--sequential-image-generation",
        choices=["disabled", "auto"],
        default="disabled",
        help="Use auto for coherent image groups, disabled for one image.",
    )
    parser.add_argument("--max-images", type=int, default=4, help="Maximum generated images when sequential generation is auto.")
    parser.add_argument("--response-format", choices=["url", "b64_json"], default="url", help="Ark response image format.")
    parser.add_argument("--stream", action="store_true", help="Enable Ark streaming image output.")
    parser.add_argument("--download", action=argparse.BooleanOptionalAction, default=True, help="Download URL outputs to local files.")
    parser.add_argument("--watermark", action=argparse.BooleanOptionalAction, default=True, help="Add Ark AI-generated watermark.")
    parser.add_argument("--output-format", choices=["png", "jpeg"], default=None, help="Seedream 5 output image format when supported.")
    parser.add_argument("--web-search", action="store_true", help="Enable Seedream web search tool when supported.")
    parser.add_argument("--optimize-prompt-mode", choices=["standard", "fast"], default=None, help="Prompt optimization mode when supported.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for Seedream 3 text-to-image.")
    parser.add_argument("--guidance-scale", type=float, default=None, help="Prompt guidance scale for Seedream 3 text-to-image.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    if args.max_images < 1 or args.max_images > 15:
        raise SystemExit("--max-images must be between 1 and 15.")
    if args.sequential_image_generation == "disabled" and args.max_images != 4:
        raise SystemExit("--max-images only applies when --sequential-image-generation auto.")
    if len(args.input_image) > 14:
        raise SystemExit("Seedream supports at most 14 input reference images.")
    if args.response_format == "url" and not args.download:
        output_hint = "The API URL is valid for about 24 hours; use --download to save files locally."
        print(output_hint, file=sys.stderr)

    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
