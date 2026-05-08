# Nano Banana Reference

Use Nano Banana for Gemini-native image generation and image editing from text, images, or both. The public product names are the preferred routing surface; the runner maps them to the Gemini API image endpoints internally.

## Variants

- `nano-banana-2`: Nano Banana 2, Gemini 3.1 Flash Image preview, balanced speed and capability. Internal API model ID: `gemini-3.1-flash-image-preview`.
- `nano-banana-pro`: Nano Banana Pro, Gemini 3 Pro Image preview, professional asset production and high-fidelity text rendering. Internal API model ID: `gemini-3-pro-image-preview`.
- `nano-banana`: Nano Banana, Gemini 2.5 Flash Image, high-volume and low-latency image tasks. Internal API model ID: `gemini-2.5-flash-image`.

Generated images include SynthID watermarking.

## Authentication

Set:

```bash
export GOOGLE_IMAGE_KEY="..."
```

## Text-to-Image

Use the bundled runner:

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/nano_banana_generate_image.py \
  --prompt "Create a clean product photo of a banana-scented perfume bottle on a white studio set" \
  --banana nano-banana-2 \
  --aspect-ratio 1:1 \
  --image-size 1K \
  --output-dir generated_images
```

Equivalent REST shape:

```bash
curl -s -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent" \
  -H "x-goog-api-key: $GOOGLE_IMAGE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [
        {"text": "Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme"}
      ]
    }],
    "generationConfig": {
      "responseModalities": ["IMAGE"]
    }
  }'
```

## Image Editing and References

Provide one or more `--input-image` paths. The script sends them as inline image parts with the prompt.

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/nano_banana_generate_image.py \
  --prompt "Place this logo naturally on a premium banana-scented perfume bottle advertisement" \
  --banana nano-banana-2 \
  --input-image logo.png \
  --aspect-ratio 4:5 \
  --image-size 2K
```

Nano Banana 3 image models can combine up to 14 reference images. Typical guidance:

- Nano Banana 2: up to 10 high-fidelity object references and up to 4 character references.
- Nano Banana Pro: up to 6 high-fidelity object references and up to 5 character references.
- Nano Banana: up to 3 input images.

For high-fidelity edits, describe protected details explicitly: faces, logos, typography, material, lighting, pose, and composition.

## Multi-Turn Editing

For iterative edits, pass prior generated images back as `--input-image` with the next prompt.

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/nano_banana_generate_image.py \
  --prompt "Keep the composition unchanged, make the headline Spanish, and preserve all graphics" \
  --banana nano-banana-2 \
  --input-image generated_images/image_1.png \
  --aspect-ratio 16:9 \
  --image-size 2K
```

When using an SDK chat session, preserve the full previous model response so thought signatures are carried forward automatically. With the bundled runner, the stable path is file-based iteration: save the image, then send it as a fresh input image.

## Google Search Grounding

Use grounding for real-time or factual visual tasks, such as weather charts, recent events, or accurate visual context.

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/nano_banana_generate_image.py \
  --prompt "Visualize the current 5-day weather forecast for San Francisco as a clean weather chart" \
  --banana nano-banana-2 \
  --google-search \
  --aspect-ratio 16:9
```

Nano Banana 2 can also use image search grounding:

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/nano_banana_generate_image.py \
  --prompt "Create a detailed painting of a Timareta butterfly resting on a flower" \
  --banana nano-banana-2 \
  --google-search \
  --image-search
```

When image search grounding is used, surface source links from `grounding_metadata` where the final user experience displays the result.

## Output Configuration

The runner supports:

- `--aspect-ratio`: examples include `1:1`, `16:9`, `9:16`, `3:2`, `2:3`, `4:5`, `5:4`, `1:4`, `4:1`, `1:8`, `8:1`, `21:9`
- `--image-size`: `512` for Nano Banana 2 when supported, or `1K`, `2K`, `4K` when supported
- `--include-text`: allow the API to return text alongside images
- `--thinking-level minimal|high`: Nano Banana 2 thinking level when supported
- `--include-thoughts`: request thought parts when supported; thought image parts are skipped when saving final output

Use uppercase `K` for `1K`, `2K`, and `4K`.

## Prompting Guidance

- Describe scenes in natural language instead of keyword lists.
- Include the intended use: product photo, icon, sticker, infographic, cover art, web hero, report visual, mockup, or concept art.
- For photography, specify angle, lens, lighting, material, background, and composition.
- For text inside images, quote the exact text and describe font style and layout.
- For edits, say what must remain unchanged.
- For complex images, give step-by-step composition instructions.
- For unwanted objects, describe the positive empty state, such as "an empty street with no traffic signs."

## Limits

- Image generation does not accept audio or video input.
- Exact requested output count is not guaranteed.
- Transparent background is not supported by Nano Banana.
- People image search grounding is currently limited.
- For best results, use supported languages including English and Chinese.
