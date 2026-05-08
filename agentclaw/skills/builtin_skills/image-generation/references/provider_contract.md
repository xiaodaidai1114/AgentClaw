# Provider Contract for Future Image Channels

Add one provider reference and one runner script per image generation channel.

## Reference File

Path:

```text
references/<provider>.md
```

Include:

- Authentication environment variables
- Supported operations: generate, edit, mask_edit, stream_generate, reference-image composition, variations when available
- Model names and recommended defaults
- Size, quality, format, compression, background, and moderation options
- Input limits for prompt length, image count, file size, and mask requirements
- Response fields containing image bytes, URLs, revised prompts, request IDs, output directories, and usage/cost metadata
- Provider-specific failure modes and retry guidance

## Runner Script

Path:

```text
scripts/<provider>_generate_image.py
```

Use this output contract:

```json
{
  "provider": "provider-name",
  "model": "model-id",
  "operation": "generate",
  "prompt": "user prompt",
  "output_dir": "generated_images",
  "absolute_output_dir": "/abs/project/generated_images",
  "output_paths": ["generated_images/image_1.png"],
  "response_id": "optional provider response id",
  "revised_prompts": ["optional revised prompt"],
  "metadata": {}
}
```

CLI arguments should stay close to the OpenAI runner where possible:

- `--prompt`
- `--output-dir`
- `--output-prefix`
- `--model`
- Provider-specific selector such as `--banana` or `--seedream`
- `--base-url` for OpenAI-compatible APIs
- `--size`
- `--quality`
- `--format`
- `--input-image`
- `--mask-image`
- `--n`
- `--stream`
- `--partial-images`

The script should print the JSON result to stdout and write generated images to disk.
