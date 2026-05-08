import base64
import py_compile
import importlib.util
import os
import re

import pytest

from agentclaw.mcp.builtin_servers.skill_tools import SkillToolsServer
from agentclaw.skills import get_builtin_skills_dir
from agentclaw.skills.parser import SkillParser


pytestmark = pytest.mark.unit


def _load_skill_script(script_name: str):
    script = get_builtin_skills_dir() / "image-generation" / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name.removesuffix(".py"), script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_image_generation_builtin_skill_loads_provider_resources():
    skill_dir = get_builtin_skills_dir() / "image-generation"
    skill = SkillParser.parse(skill_dir)

    assert skill.name == "image-generation"
    assert skill.description.startswith("Generate, edit, and iterate raster images")
    assert "visual asset creation" in skill.description
    assert "reference images" in skill.description
    assert "do not" not in skill.description.lower()
    assert "don't" not in skill.description.lower()

    reference_names = {path.name for path in skill.references}
    script_names = {path.name for path in skill.scripts}
    assert {"openai.md", "nano_banana.md", "seedream.md", "provider_contract.md"}.issubset(reference_names)
    assert "openai_generate_image.py" in script_names
    assert "nano_banana_generate_image.py" in script_names
    assert "seedream_generate_image.py" in script_names


def test_openai_image_generation_script_is_valid_python():
    script = (
        get_builtin_skills_dir()
        / "image-generation"
        / "scripts"
        / "openai_generate_image.py"
    )

    py_compile.compile(str(script), doraise=True)


def test_image_generation_scripts_return_output_directory(tmp_path, monkeypatch):
    image_base64 = base64.b64encode(b"image-bytes").decode("utf-8")

    openai_module = _load_skill_script("openai_generate_image.py")

    class FakeOpenAIImages:
        def generate(self, **_request):
            return {"id": "openai-test", "data": [{"b64_json": image_base64}]}

    class FakeOpenAIClient:
        images = FakeOpenAIImages()

    monkeypatch.setattr(openai_module, "_openai_client", lambda _args: FakeOpenAIClient())
    openai_args = openai_module.parse_args(["--prompt", "test", "--output-dir", str(tmp_path / "openai")])
    openai_result = openai_module.run_generate(openai_args)

    assert openai_result["output_dir"] == str(tmp_path / "openai")
    assert openai_result["absolute_output_dir"] == str((tmp_path / "openai").resolve())

    nano_module = _load_skill_script("nano_banana_generate_image.py")
    monkeypatch.setattr(
        nano_module,
        "_request_json",
        lambda _model_id, _payload: {
            "responseId": "nano-test",
            "candidates": [{"content": {"parts": [{"inline_data": {"mime_type": "image/png", "data": image_base64}}]}}],
        },
    )
    nano_args = nano_module.parse_args(["--prompt", "test", "--output-dir", str(tmp_path / "nano")])
    nano_result = nano_module.run(nano_args)

    assert nano_result["output_dir"] == str(tmp_path / "nano")
    assert nano_result["absolute_output_dir"] == str((tmp_path / "nano").resolve())

    seedream_module = _load_skill_script("seedream_generate_image.py")
    monkeypatch.setattr(
        seedream_module,
        "_post_json",
        lambda _payload: {"id": "seedream-test", "data": [{"b64_json": image_base64}]},
    )
    seedream_args = seedream_module.parse_args([
        "--prompt",
        "test",
        "--output-dir",
        str(tmp_path / "seedream"),
        "--response-format",
        "b64_json",
    ])
    seedream_result = seedream_module.run(seedream_args)

    assert seedream_result["output_dir"] == str(tmp_path / "seedream")
    assert seedream_result["absolute_output_dir"] == str((tmp_path / "seedream").resolve())


def test_openai_image_generation_script_validates_streaming_options():
    script = (
        get_builtin_skills_dir()
        / "image-generation"
        / "scripts"
        / "openai_generate_image.py"
    )
    spec = importlib.util.spec_from_file_location("openai_generate_image", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit, match="--partial-images requires --stream"):
        module.main(["--prompt", "test", "--partial-images", "2"])


def test_openai_image_generation_script_uses_gpt_image_api_only():
    script = (
        get_builtin_skills_dir()
        / "image-generation"
        / "scripts"
        / "openai_generate_image.py"
    )
    spec = importlib.util.spec_from_file_location("openai_generate_image", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args(["--prompt", "test"])

    assert args.model == "gpt-image-2"
    assert args.output_dir == "generated_images"
    assert not hasattr(args, "api")
    assert not hasattr(args, "previous_response_id")


def test_openai_image_generation_script_supports_base_url_override(monkeypatch):
    module = _load_skill_script("openai_generate_image.py")

    monkeypatch.setenv("OPENAI_IMAGE_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.squarefaceicon.org/v1")

    args = module.parse_args(["--prompt", "test"])

    assert args.base_url is None
    assert module.resolve_base_url(args) == "https://api.squarefaceicon.org/v1"
    assert module.resolve_api_key() == "test-key"


def test_image_generation_provider_env_names_are_deduplicated():
    skill_dir = get_builtin_skills_dir() / "image-generation"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in skill_dir.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py"}
    )

    assert "OPENAI_IMAGE_API_KEY" not in text
    assert "OPENAI_IMAGE_BASE_URL" not in text
    assert "GEMINI_API_KEY" not in text
    assert "VOLCENGINE_ARK_API_KEY" not in text
    assert "OPENAI_API_KEY" not in text
    assert "GOOGLE_API_KEY" not in text
    assert "OPENAI_IMAGE_KEY" in text
    assert "OPENAI_BASE_URL" in text
    assert "GOOGLE_IMAGE_KEY" in text
    assert "ARK_API_KEY" in text


def test_image_generation_scripts_load_project_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_IMAGE_KEY=openai-from-env-file",
                "OPENAI_BASE_URL=https://image.example/v1",
                "GOOGLE_IMAGE_KEY=google-from-env-file",
                "ARK_API_KEY=ark-from-env-file",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for key in ["OPENAI_IMAGE_KEY", "OPENAI_BASE_URL", "GOOGLE_IMAGE_KEY", "ARK_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    openai_module = _load_skill_script("openai_generate_image.py")
    nano_module = _load_skill_script("nano_banana_generate_image.py")
    seedream_module = _load_skill_script("seedream_generate_image.py")
    for module in [openai_module, nano_module, seedream_module]:
        monkeypatch.setattr(module, "PROJECT_DIR", tmp_path)

    openai_args = openai_module.parse_args(["--prompt", "test"])

    assert openai_module.resolve_api_key() == "openai-from-env-file"
    assert openai_module.resolve_base_url(openai_args) == "https://image.example/v1"
    assert nano_module._api_key() == "google-from-env-file"
    assert seedream_module._api_key() == "ark-from-env-file"
    assert os.environ["OPENAI_IMAGE_KEY"] == "openai-from-env-file"
    assert os.environ["GOOGLE_IMAGE_KEY"] == "google-from-env-file"
    assert os.environ["ARK_API_KEY"] == "ark-from-env-file"


def test_nano_banana_script_uses_single_google_image_key(monkeypatch):
    module = _load_skill_script("nano_banana_generate_image.py")

    monkeypatch.setenv("GOOGLE_IMAGE_KEY", "google-key")

    assert module._api_key() == "google-key"


def test_seedream_script_uses_single_ark_api_key(monkeypatch):
    module = _load_skill_script("seedream_generate_image.py")

    monkeypatch.setenv("ARK_API_KEY", "ark-key")

    assert module._api_key() == "ark-key"


def test_nano_banana_generation_script_uses_banana_aliases():
    script = (
        get_builtin_skills_dir()
        / "image-generation"
        / "scripts"
        / "nano_banana_generate_image.py"
    )
    spec = importlib.util.spec_from_file_location("nano_banana_generate_image", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args(["--prompt", "test"])

    assert args.banana == "nano-banana-2"
    assert args.output_dir == "generated_images"
    assert not hasattr(args, "model")
    assert module.resolve_model_id("nano-banana-2") == "gemini-3.1-flash-image-preview"
    assert module.resolve_model_id("nano-banana-pro") == "gemini-3-pro-image-preview"


def test_seedream_generation_script_uses_seedream_aliases():
    script = (
        get_builtin_skills_dir()
        / "image-generation"
        / "scripts"
        / "seedream_generate_image.py"
    )
    spec = importlib.util.spec_from_file_location("seedream_generate_image", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.parse_args(["--prompt", "test"])

    assert args.seedream == "seedream-5"
    assert args.output_dir == "generated_images"
    assert module.resolve_model_id(args) == "doubao-seedream-5-0-260128"
    assert module.resolve_operation(args) == "text_to_image"


def test_seedream_generation_script_rejects_secret_literal():
    skill_dir = get_builtin_skills_dir() / "image-generation"
    hardcoded_bearer = re.compile(r"Authorization:\s*Bearer\s+(?!\$)[A-Za-z0-9._-]{8,}")

    for path in skill_dir.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".json"}:
            text = path.read_text(encoding="utf-8")
            assert not hardcoded_bearer.search(text)


def test_image_generation_skill_documents_key_and_output_directory_flow():
    skill_doc = (get_builtin_skills_dir() / "image-generation" / "SKILL.md").read_text(encoding="utf-8")

    assert ".env" in skill_doc
    assert "temporary environment" in skill_doc
    assert "generated_images" in skill_doc
    assert "output_dir" in skill_doc


@pytest.mark.asyncio
async def test_image_generation_builtin_skill_can_be_read_by_skill_tool(tmp_path):
    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    skill_doc = await server._read_skill_file(
        {"skill_name": "image-generation", "file_name": "SKILL.md"}
    )
    openai_reference = await server._read_skill_file(
        {"skill_name": "image-generation", "file_name": "references/openai.md"}
    )
    nano_reference = await server._read_skill_file(
        {"skill_name": "image-generation", "file_name": "references/nano_banana.md"}
    )
    seedream_reference = await server._read_skill_file(
        {"skill_name": "image-generation", "file_name": "references/seedream.md"}
    )

    assert "[OK] Read skill file: image-generation/SKILL.md" in skill_doc
    assert "OpenAI GPT Image" in skill_doc
    assert "[OK] Read skill file: image-generation/references/openai.md" in openai_reference
    assert "Image API" in openai_reference
    assert "gpt-image-2" in openai_reference
    assert "Responses API" not in openai_reference
    assert "gpt-5.5" not in openai_reference
    assert "[OK] Read skill file: image-generation/references/nano_banana.md" in nano_reference
    assert "Nano Banana 2" in nano_reference
    assert "nano-banana-pro" in nano_reference
    assert "Gemini 3.1 Flash Image" in nano_reference
    assert "[OK] Read skill file: image-generation/references/seedream.md" in seedream_reference
    assert "Seedream 5" in seedream_reference
    assert "ARK_API_KEY" in seedream_reference
    assert "VOLCENGINE_ARK_API_KEY" not in seedream_reference
    assert "sequential_image_generation" in seedream_reference
