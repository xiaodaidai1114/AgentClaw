# OpenAI GPT Image Reference

This skill uses the OpenAI Image API with GPT Image models only. Default to `gpt-image-2` unless the user or project configuration names another `gpt-image-*` model.

Some GPT Image models may require API Organization Verification before use.

## Authentication and Base URL

For official OpenAI or an OpenAI-compatible GPT Image provider, set one key:

```bash
export OPENAI_IMAGE_KEY="..."
```

For OpenAI-compatible GPT Image providers, optionally set the endpoint override:

```bash
export OPENAI_BASE_URL="https://api.example.com/v1"
```

Or pass `--base-url` to the runner. If no base URL is provided, the runner uses the official OpenAI default.

Example:

```bash
python agentclaw/skills/builtin_skills/image-generation/scripts/openai_generate_image.py \
  --prompt "A friendly square face icon with glossy lighting" \
  --base-url https://api.squarefaceicon.org/v1 \
  --model gpt-image-2 \
  --size 1024x1024 \
  --quality medium
```

## Text-to-Image Generation

Use `client.images.generate` for a prompt that creates one or more new images.

```python
from openai import OpenAI
import base64

client = OpenAI()

prompt = """
A polished editorial illustration of a desktop automation workspace,
showing browser, file, and workflow controls connected by luminous nodes.
"""

result = client.images.generate(
    model="gpt-image-2",
    prompt=prompt,
)

image_base64 = result.data[0].b64_json
image_bytes = base64.b64decode(image_base64)

with open("automation-workspace.png", "wb") as f:
    f.write(image_bytes)
```

Common generation parameters:

- `model`: `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1`, or `gpt-image-1-mini`
- `prompt`: text brief for the image
- `n`: number of images to generate when supported
- `size`: `auto` or dimensions such as `1024x1024`
- `quality`: `low`, `medium`, `high`, or `auto`
- `output_format`: `png`, `jpeg`, or `webp`
- `output_compression`: `0` to `100`, for JPEG/WebP
- `background`: `auto`, `opaque`, or provider-supported transparent modes
- `moderation`: `auto` or `low`

## Streaming Generation

Use Image API streaming when partial images are useful for a more interactive experience. `partial_images` accepts `0` to `3`.

```python
from openai import OpenAI
import base64

client = OpenAI()

stream = client.images.generate(
    prompt="Draw a river made of white silk ribbons through a serene winter landscape",
    model="gpt-image-2",
    stream=True,
    partial_images=2,
)

for event in stream:
    if event.type == "image_generation.partial_image":
        idx = event.partial_image_index
        image_bytes = base64.b64decode(event.b64_json)
        with open(f"river{idx}.png", "wb") as f:
            f.write(image_bytes)
```

## Image Edits and Reference Images

Use `client.images.edit` to modify existing images or create a new image using one or more references.

```python
from openai import OpenAI
import base64

client = OpenAI()

prompt = """
Generate a photorealistic image of a gift basket on a white background
labeled 'Relax & Unwind' with a ribbon and handwriting-like font,
containing all the items in the reference pictures.
"""

result = client.images.edit(
    model="gpt-image-2",
    image=[
        open("body-lotion.png", "rb"),
        open("bath-bomb.png", "rb"),
        open("incense-kit.png", "rb"),
        open("soap.png", "rb"),
    ],
    prompt=prompt,
)

image_base64 = result.data[0].b64_json
image_bytes = base64.b64decode(image_base64)

with open("gift-basket.png", "wb") as f:
    f.write(image_bytes)
```

When calling from a script, close opened file handles after the API call. For multiple reference images, pass a list of file objects.

## Masked Edits

Use `mask` when the user identifies an area to replace. If multiple input images are provided, the mask applies to the first image.

```python
from openai import OpenAI
import base64

client = OpenAI()

result = client.images.edit(
    model="gpt-image-2",
    image=open("sunlit_lounge.png", "rb"),
    mask=open("mask.png", "rb"),
    prompt="A sunlit indoor lounge area with a pool containing a flamingo",
)

image_base64 = result.data[0].b64_json
image_bytes = base64.b64decode(image_base64)

with open("composition.png", "wb") as f:
    f.write(image_bytes)
```

Mask requirements:

- The source image and mask should have the same format and dimensions.
- Each file must be less than 50 MB.
- The mask should include an alpha channel.
- Masking is prompt-guided and may not follow the exact pixel boundary perfectly.

Add an alpha channel to a black and white mask when needed:

```python
from io import BytesIO
from PIL import Image

mask = Image.open(img_path_mask).convert("L")
mask_rgba = mask.convert("RGBA")
mask_rgba.putalpha(mask)

buf = BytesIO()
mask_rgba.save(buf, format="PNG")
mask_bytes = buf.getvalue()

with open("mask_alpha.png", "wb") as f:
    f.write(mask_bytes)
```

## Size and Quality

Popular sizes:

- `1024x1024`
- `1536x1024`
- `1024x1536`
- `2048x2048`
- `2048x1152`
- `3840x2160`
- `2160x3840`
- `auto`

For `gpt-image-2`, generated dimensions should satisfy these constraints:

- Maximum edge length at most `3840px`
- Both edges are multiples of `16px`
- Long edge to short edge ratio at most `3:1`
- Total pixels from `655,360` to `8,294,400`

Quality values:

- `low`: fastest drafts, thumbnails, and quick iterations
- `medium`: balanced output
- `high`: final-quality assets
- `auto`: provider selects from the prompt

Outputs above `2560x1440` total pixels are experimental. Square images are typically fastest.

## Format, Background, and Moderation

Output formats:

- `png`: default, lossless
- `jpeg`: often faster for photographic images
- `webp`: compact web delivery

JPEG and WebP support `output_compression` from `0` to `100`.

Background support depends on the model. `gpt-image-2` currently does not support transparent backgrounds.

Moderation values:

- `auto`: standard filtering
- `low`: less restrictive filtering, when the model and account allow it

## Practical Limits

- Complex prompts may take up to about two minutes.
- Text rendering can still need iteration for exact spelling, placement, or brand typography.
- Character consistency and exact layout composition may need reference images plus multiple passes.
- For `gpt-image-2`, image edits with references are processed at high input fidelity automatically.
- Cost is affected by input text tokens, input image tokens for edits, output image tokens, requested size, quality, and streamed partial images.
