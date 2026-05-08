#!/usr/bin/env python3
"""Generate or edit images with OpenAI GPT Image models."""

from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
import json
import os
import sys
from pathlib import Path
from typing import Any


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


def resolve_base_url(args: argparse.Namespace) -> str | None:
    _load_project_env()
    base_url = (args.base_url or os.getenv("OPENAI_BASE_URL") or "").strip()
    return base_url.rstrip("/") if base_url else None


def resolve_api_key() -> str:
    _load_project_env()
    api_key = (os.getenv("OPENAI_IMAGE_KEY") or "").strip()
    if not api_key:
        raise SystemExit("OPENAI_IMAGE_KEY is required for OpenAI-compatible image generation.")
    return api_key


def _openai_client(args: argparse.Namespace):
    _load_project_env()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("The openai package is required. Install agentclaw-ai or `pip install openai`.") from exc

    client_options: dict[str, Any] = {"api_key": resolve_api_key()}
    base_url = resolve_base_url(args)
    if base_url:
        client_options["base_url"] = base_url
    return OpenAI(**client_options)


def _attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _write_b64_image(image_base64: str, output_dir: Path, output_prefix: str, index: int, output_format: str) -> str:
    suffix = output_format.lower().lstrip(".") or "png"
    output_path = output_dir / f"{output_prefix}_{index}.{suffix}"
    output_path.write_bytes(base64.b64decode(image_base64))
    return str(output_path)


def _extract_image_api_b64_items(response: Any) -> list[str]:
    images: list[str] = []
    for item in _attr_or_key(response, "data", []) or []:
        image_base64 = _attr_or_key(item, "b64_json") or _attr_or_key(item, "result")
        if image_base64:
            images.append(str(image_base64))
    return images


def _extract_revised_prompts(response: Any) -> list[str]:
    prompts: list[str] = []
    for item in _attr_or_key(response, "data", []) or []:
        revised_prompt = _attr_or_key(item, "revised_prompt")
        if revised_prompt:
            prompts.append(str(revised_prompt))
    return prompts


def _add_optional_image_params(request: dict[str, Any], args: argparse.Namespace) -> None:
    optional_values = {
        "size": args.size,
        "quality": args.quality,
        "output_format": args.output_format,
        "output_compression": args.output_compression,
        "background": args.background,
        "moderation": args.moderation,
    }
    for key, value in optional_values.items():
        if value is not None:
            request[key] = value


def _operation(args: argparse.Namespace) -> str:
    if args.mask_image:
        return "mask_edit"
    if args.input_image:
        return "edit"
    return "generate"


def _validate_paths(paths: list[str], label: str) -> None:
    for path in paths:
        if not Path(path).is_file():
            raise SystemExit(f"{label} file not found: {path}")


def run_generate(args: argparse.Namespace) -> dict[str, Any]:
    client = _openai_client(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    request: dict[str, Any] = {
        "model": args.model,
        "prompt": args.prompt,
        "n": args.n,
    }
    _add_optional_image_params(request, args)

    if args.stream:
        return run_generate_stream(args, client, request, output_dir)

    response = client.images.generate(**request)
    images = _extract_image_api_b64_items(response)
    output_paths = [
        _write_b64_image(image_base64, output_dir, args.output_prefix, index, args.output_format)
        for index, image_base64 in enumerate(images, start=1)
    ]

    return {
        "provider": "openai",
        "api": "images",
        "model": request["model"],
        "operation": "generate",
        "prompt": args.prompt,
        "output_dir": str(output_dir),
        "absolute_output_dir": str(output_dir.resolve()),
        "output_paths": output_paths,
        "response_id": _attr_or_key(response, "id"),
        "revised_prompts": _extract_revised_prompts(response),
        "metadata": {"base_url": resolve_base_url(args) or "openai", "image_count": len(output_paths), "stream": False},
    }


def run_generate_stream(
    args: argparse.Namespace,
    client: Any,
    request: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    stream_request = dict(request)
    stream_request["stream"] = True
    if args.partial_images is not None:
        stream_request["partial_images"] = args.partial_images

    output_paths: list[str] = []
    partial_paths: list[str] = []
    response_id: str | None = None

    for event in client.images.generate(**stream_request):
        event_type = _attr_or_key(event, "type", "")
        response_id = _attr_or_key(event, "id", response_id)

        if event_type == "image_generation.partial_image":
            image_base64 = _attr_or_key(event, "b64_json")
            partial_index = int(_attr_or_key(event, "partial_image_index", len(partial_paths)))
            if image_base64:
                path = _write_b64_image(
                    str(image_base64),
                    output_dir,
                    f"{args.output_prefix}_partial",
                    partial_index,
                    args.output_format,
                )
                partial_paths.append(path)
                output_paths.append(path)
            continue

        image_base64 = _attr_or_key(event, "b64_json")
        if image_base64:
            output_paths.append(
                _write_b64_image(
                    str(image_base64),
                    output_dir,
                    args.output_prefix,
                    len(output_paths) + 1,
                    args.output_format,
                )
            )

    return {
        "provider": "openai",
        "api": "images",
        "model": request["model"],
        "operation": "stream_generate",
        "prompt": args.prompt,
        "output_dir": str(output_dir),
        "absolute_output_dir": str(output_dir.resolve()),
        "output_paths": output_paths,
        "response_id": response_id,
        "revised_prompts": [],
        "metadata": {
            "base_url": resolve_base_url(args) or "openai",
            "image_count": len(output_paths),
            "stream": True,
            "partial_image_count": len(partial_paths),
            "partial_output_paths": partial_paths,
        },
    }


def run_edit(args: argparse.Namespace) -> dict[str, Any]:
    client = _openai_client(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _validate_paths(args.input_image, "--input-image")
    if args.mask_image:
        _validate_paths([args.mask_image], "--mask-image")

    request: dict[str, Any] = {
        "model": args.model,
        "prompt": args.prompt,
    }
    _add_optional_image_params(request, args)

    with ExitStack() as stack:
        image_files = [stack.enter_context(Path(path).open("rb")) for path in args.input_image]
        request["image"] = image_files[0] if len(image_files) == 1 else image_files
        if args.mask_image:
            request["mask"] = stack.enter_context(Path(args.mask_image).open("rb"))

        response = client.images.edit(**request)

    images = _extract_image_api_b64_items(response)
    output_paths = [
        _write_b64_image(image_base64, output_dir, args.output_prefix, index, args.output_format)
        for index, image_base64 in enumerate(images, start=1)
    ]

    return {
        "provider": "openai",
        "api": "images",
        "model": request["model"],
        "operation": _operation(args),
        "prompt": args.prompt,
        "output_dir": str(output_dir),
        "absolute_output_dir": str(output_dir.resolve()),
        "output_paths": output_paths,
        "response_id": _attr_or_key(response, "id"),
        "revised_prompts": _extract_revised_prompts(response),
        "metadata": {
            "base_url": resolve_base_url(args) or "openai",
            "image_count": len(output_paths),
            "input_image_count": len(args.input_image),
            "mask_image": args.mask_image,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit images with OpenAI GPT Image models.")
    parser.add_argument("--prompt", required=True, help="Text prompt for image generation or editing.")
    parser.add_argument("--model", default="gpt-image-2", help="GPT Image model ID. Defaults to gpt-image-2.")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL. Defaults to official OpenAI.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for generated image files.")
    parser.add_argument("--output-prefix", default="image", help="Filename prefix for generated image files.")
    parser.add_argument("--n", type=int, default=1, help="Number of images for text-to-image generation.")
    parser.add_argument("--size", default=None, help="Image size such as 1024x1024, 1536x1024, 1024x1536, or auto.")
    parser.add_argument("--quality", default=None, help="Quality such as low, medium, high, or auto.")
    parser.add_argument(
        "--format",
        dest="output_format",
        default="png",
        choices=["png", "jpeg", "webp"],
        help="Output file format.",
    )
    parser.add_argument("--output-compression", type=int, default=None, help="JPEG/WebP compression level from 0 to 100.")
    parser.add_argument("--background", default=None, help="Background mode such as auto, opaque, or transparent when supported.")
    parser.add_argument("--moderation", default=None, help="Moderation strictness such as auto or low when supported.")
    parser.add_argument("--stream", action="store_true", help="Stream image generation and save partial image events.")
    parser.add_argument("--partial-images", type=int, default=None, help="Partial image count from 0 to 3 for streaming generation.")
    parser.add_argument("--input-image", action="append", default=[], help="Reference/source image path for image edits. Repeat for multiple images.")
    parser.add_argument("--mask-image", default=None, help="Mask image path for masked edits. Applies to the first input image.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    if args.n < 1:
        raise SystemExit("--n must be at least 1.")
    if args.output_compression is not None and not 0 <= args.output_compression <= 100:
        raise SystemExit("--output-compression must be between 0 and 100.")
    if args.partial_images is not None:
        if not args.stream:
            raise SystemExit("--partial-images requires --stream.")
        if not 0 <= args.partial_images <= 3:
            raise SystemExit("--partial-images must be between 0 and 3.")
    if args.mask_image and not args.input_image:
        raise SystemExit("--mask-image requires at least one --input-image.")
    if args.stream and args.input_image:
        raise SystemExit("--stream is only supported for text-to-image generation.")

    result = run_edit(args) if args.input_image else run_generate(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
