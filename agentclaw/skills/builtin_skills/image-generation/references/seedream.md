# Seedream Reference

Use Seedream for image generation through Volcengine Ark. This provider supports text-to-image, image-to-image, multi-reference image generation, coherent image groups, streaming output, web search, and watermarked or unwatermarked outputs depending on account permissions and model support.

## Authentication

Set:

```bash
export ARK_API_KEY="..."
```

The API endpoint is:

```text
POST https://ark.cn-beijing.volces.com/api/v3/images/generations
```

Use `Authorization: Bearer $ARK_API_KEY`. Keep API keys out of skill files, logs, prompts, tests, and examples.

## Variants

- `seedream-5`: default alias for `doubao-seedream-5-0-260128`, matching Seedream 5.0 image generation examples.

Use `--model-id` only when the project needs a specific Ark Model ID or Endpoint ID.

## Text-to-Image Single Image

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/seedream_generate_image.py \
  --prompt "Interstellar black hole scene with a damaged vintage train bursting through, cinematic impact, deep blue lighting" \
  --seedream seedream-5 \
  --sequential-image-generation disabled \
  --response-format url \
  --size 2K \
  --watermark
```

Equivalent REST shape:

```bash
curl -X POST https://ark.cn-beijing.volces.com/api/v3/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -d '{
    "model": "doubao-seedream-5-0-260128",
    "prompt": "A cinematic black hole scene with a vintage train bursting through",
    "sequential_image_generation": "disabled",
    "response_format": "url",
    "size": "2K",
    "stream": false,
    "watermark": true
  }'
```

## Text-to-Image Group

Use `--sequential-image-generation auto` for coherent image groups.

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/seedream_generate_image.py \
  --prompt "Generate four coherent illustrations of the same courtyard across the four seasons" \
  --seedream seedream-5 \
  --sequential-image-generation auto \
  --max-images 4 \
  --response-format url \
  --size 2K \
  --stream
```

The generated image count is controlled by both the prompt and `--max-images`.

## Image-to-Image

Pass a reference image as a URL, a data URL, or a local path. Local paths are encoded as `data:image/<format>;base64,...`.

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/seedream_generate_image.py \
  --prompt "Generate a close-up image of the dog lying on grass" \
  --input-image reference.png \
  --seedream seedream-5 \
  --sequential-image-generation disabled \
  --size 2K
```

For multiple reference images:

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/seedream_generate_image.py \
  --prompt "Change the outfit in image 1 to the outfit in image 2" \
  --input-image person.png \
  --input-image outfit.png \
  --seedream seedream-5 \
  --size 2K
```

For multi-reference groups:

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/seedream_generate_image.py \
  --prompt "Generate three images of a girl and a cow plush toy happily riding a roller coaster: morning, noon, and night" \
  --input-image girl.png \
  --input-image plush.png \
  --sequential-image-generation auto \
  --max-images 3 \
  --stream
```

## Web Search

Seedream 5 supports a web search tool. Use it for time-sensitive or fact-grounded images such as products, weather, maps, and recent events.

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/seedream_generate_image.py \
  --prompt "Create a current weather-themed poster for Beijing today" \
  --seedream seedream-5 \
  --web-search \
  --size 2K
```

The response usage may include `usage.tool_usage.web_search`. A value of `0` means no search was used.

## Size

Seedream 5 supports two size styles:

- Resolution keywords: `2K`, `3K`, `4K`
- Pixel dimensions: examples include `2048x2048`, `2848x1600`, `1600x2848`, `2496x1664`, `3136x1344`

When using pixel dimensions, total pixels and aspect ratio must satisfy Ark limits. Recommended 2K examples:

- `2048x2048` for `1:1`
- `2304x1728` for `4:3`
- `1728x2304` for `3:4`
- `2848x1600` for `16:9`
- `1600x2848` for `9:16`
- `2496x1664` for `3:2`
- `1664x2496` for `2:3`
- `3136x1344` for `21:9`

## Key Parameters

- `prompt`: required, supports Chinese and English. Keep prompts focused; a practical limit is about 300 Chinese characters or 600 English words.
- `image`: URL, data URL, or list of images for reference-based generation.
- `sequential_image_generation`: `disabled` for one output image, `auto` for coherent image groups.
- `sequential_image_generation_options.max_images`: `1` to `15`; input reference image count plus generated image count should be at most `15`.
- `response_format`: `url` or `b64_json`. URLs expire after about 24 hours; the runner downloads them by default.
- `stream`: return each generated image as it becomes available when supported.
- `watermark`: whether to add the Ark AI-generated watermark.
- `output_format`: `png` or `jpeg` when supported by Seedream 5.
- `optimize_prompt_options.mode`: `standard` or `fast` when supported.
- `seed` and `guidance_scale`: Seedream 3 text-to-image only.

## Input Limits

- Seedream 5 supports up to 14 reference images.
- For Seedream 5 group generation, reference image count plus generated image count should be at most 15.
- A single input image should be no larger than 10 MB.
- Single image total pixels should be no larger than `6000x6000`.
- Supported input formats include URL and base64 data URL. Common formats include jpeg and png; Seedream 5 also supports webp, bmp, tiff, and gif.

## Response Handling

Non-stream responses include:

- `model`
- `created`
- `data`: list of generated image objects or per-image errors
- `data.url`: image URL when `response_format=url`
- `data.b64_json`: base64 image when `response_format=b64_json`
- `data.size`: generated image dimensions for supported models
- `usage.generated_images`
- `usage.output_tokens`
- `usage.total_tokens`
- `usage.tool_usage.web_search` when web search is enabled

The bundled runner prints a JSON result and saves generated images locally. For URL responses, it downloads the image immediately because Ark URLs expire.

## Failure Handling

For coherent image groups, one image may fail while others succeed. If an item has `data.error`, report the code and message and still return successfully generated files. If the request-level response has `error`, treat it as a failed generation request.
