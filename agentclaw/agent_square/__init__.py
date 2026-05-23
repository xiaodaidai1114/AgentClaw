"""Packaged Claw App templates shipped with AgentClaw.

The public product surface calls these templates the "Template Library".  The
internal package name remains ``agent_square`` for compatibility, but listing
templates must stay side-effect free: reading a manifest should never import or
register a workflow.  A template only becomes a project workflow after the user
explicitly imports it.
"""

from __future__ import annotations

import importlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


AGENT_SQUARE_DIR = Path(__file__).resolve().parent
APP_PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_app_manifest(manifest_path: Path) -> dict[str, Any]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    app_dir = manifest_path.parent

    workflow = data.get("workflow") or data.get("entry")
    entry = data.get("entry") or workflow
    workflow_id = data.get("workflow_id") or data.get("id")

    data["entry"] = entry
    data["workflow"] = workflow
    data["workflow_id"] = workflow_id

    if workflow:
        data["workflow_path"] = str((app_dir / workflow).resolve())
    if entry:
        data["entry_path"] = str((app_dir / entry).resolve())
    data["app_dir"] = str(app_dir.resolve())
    data["registered"] = _is_workflow_registered(str(workflow_id or ""))
    return data


def _is_workflow_registered(workflow_id: str) -> bool:
    if not workflow_id:
        return False
    try:
        from agentclaw.api.registry import WorkflowRegistry

        return WorkflowRegistry.get(workflow_id) is not None
    except Exception:
        return False


def list_claw_apps() -> list[dict[str, Any]]:
    """Return packaged Claw App manifests sorted by display name."""
    apps: list[dict[str, Any]] = []
    for manifest_path in AGENT_SQUARE_DIR.glob("*/claw_app.json"):
        try:
            apps.append(_load_app_manifest(manifest_path))
        except Exception:
            continue
    return sorted(apps, key=lambda app: (str(app.get("category", "")), str(app.get("name", ""))))


def get_claw_app(app_id: str) -> dict[str, Any] | None:
    """Return a packaged Claw App manifest by id."""
    for app in list_claw_apps():
        if app.get("id") == app_id:
            return app
    return None


def _safe_package_name(raw_name: str) -> str:
    """Return a Python package-safe name or raise for unsupported ids."""
    name = str(raw_name or "").strip()
    if not APP_PACKAGE_RE.fullmatch(name):
        raise ValueError(f"template id must be a valid Python package name: {raw_name}")
    return name


def _safe_alias(raw_name: str) -> str:
    alias = re.sub(r"\W", "_", str(raw_name or "").strip())
    if not alias or alias[0].isdigit():
        alias = f"template_{alias}"
    return alias


def _project_agents_dir(project_dir: Path) -> Path:
    return Path(project_dir).expanduser().resolve() / "agents"


def _target_dir_for_app(app_id: str, project_dir: Path) -> Path:
    return _project_agents_dir(project_dir) / _safe_package_name(app_id)


def _workflow_entry_module(entry: str) -> str:
    entry_path = Path(str(entry or ""))
    if entry_path.suffix == ".py":
        entry_path = entry_path.with_suffix("")
    return ".".join(part for part in entry_path.parts if part and part != ".")


def _workflow_module_name(app: dict[str, Any]) -> str:
    app_dir = Path(str(app.get("app_dir") or "")).resolve()
    package_dir = AGENT_SQUARE_DIR.resolve()
    try:
        app_package = app_dir.relative_to(package_dir)
    except ValueError as exc:
        raise ValueError(f"template app directory is outside agent_square: {app_dir}") from exc
    if len(app_package.parts) != 1:
        raise ValueError(f"template app directory must be a direct child of agent_square: {app_dir}")
    return f"agentclaw.agent_square.{app_package.name}.{_workflow_entry_module(str(app.get('workflow') or app.get('entry') or ''))}"


def _project_workflow_module_name(app_id: str, entry: str) -> str:
    return f"agents.{_safe_package_name(app_id)}.{_workflow_entry_module(entry)}"


def _copy_ignore(_: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name == "__pycache__"
        or name == ".pytest_cache"
        or name.endswith(".pyc")
        or name.endswith(".pyo")
    }


def _cleanup_imported_template_resources(target_dir: Path) -> None:
    # A template's top-level skills/ directory is data, not a Python package.
    # Keeping __init__.py here makes Workflow skip the directory during
    # automatic skill discovery.
    skills_init = target_dir / "skills" / "__init__.py"
    if skills_init.exists():
        skills_init.unlink()


def get_claw_app_import_status(app_id: str, project_dir: str | Path) -> dict[str, Any]:
    """Return whether a packaged template has been imported into a project."""
    project_path = Path(project_dir).expanduser().resolve()
    app = get_claw_app(app_id)
    if not app:
        return {
            "imported": False,
            "registered": False,
            "target_dir": "",
            "workflow_file": "",
        }

    target_dir = _target_dir_for_app(str(app.get("id") or app_id), project_path)
    workflow_file = target_dir / str(app.get("workflow") or app.get("entry") or "")
    workflow_id = str(app.get("workflow_id") or app.get("id") or "")
    imported = target_dir.is_dir() and workflow_file.is_file()
    return {
        "imported": imported,
        "registered": _is_workflow_registered(workflow_id),
        "target_dir": str(target_dir),
        "workflow_file": str(workflow_file),
    }


def _import_existing_claw_app_from_project(app: dict[str, Any], project_path: Path) -> dict[str, Any]:
    app_package = _safe_package_name(str(app.get("id") or ""))
    target_dir = _target_dir_for_app(app_package, project_path)
    _cleanup_imported_template_resources(target_dir)
    entry = str(app.get("entry") or app.get("workflow") or "")
    workflow_file = (target_dir / entry).resolve()
    if not workflow_file.is_file():
        raise FileNotFoundError(f"workflow file not found after import: {workflow_file}")

    import_info = _ensure_project_import(
        project_path,
        app_package,
        entry,
        str(app.get("workflow_id") or app.get("id") or app_package),
    )

    return {
        "app": app,
        "project_dir": str(project_path),
        "target_dir": str(target_dir),
        "workflow_file": str(workflow_file),
        "workflow_id": str(app.get("workflow_id") or app.get("id") or app_package),
        **import_info,
    }


def _ensure_project_import(
    project_dir: Path,
    app_id: str,
    entry: str,
    workflow_id: str,
) -> dict[str, Any]:
    agents_dir = _project_agents_dir(project_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)
    init_path = agents_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text('"""Project workflows imported by AgentClaw."""\n', encoding="utf-8")

    module_path = f".{_safe_package_name(app_id)}.{_workflow_entry_module(entry)}"
    alias = _safe_alias(f"{workflow_id}_workflow")
    marker = f"# AgentClaw template import: {app_id}"
    import_line = f"from {module_path} import workflow as {alias}  # noqa: F401"

    text = init_path.read_text(encoding="utf-8")
    if import_line in text:
        return {"init_path": str(init_path), "import_added": False, "import_line": import_line}

    prefix = "" if text.endswith("\n") or not text else "\n"
    init_path.write_text(f"{text}{prefix}{marker}\n{import_line}\n", encoding="utf-8")
    return {"init_path": str(init_path), "import_added": True, "import_line": import_line}


def import_claw_app_to_project(
    app_id: str,
    project_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy a packaged template into a project without registering it as builtin.

    Files are copied to ``<project>/agents/<app_id>/`` and ``agents/__init__.py``
    is updated so the workflow will register again after a service restart.
    Runtime hot-registration is handled by the API service layer.
    """
    app = get_claw_app(app_id)
    if not app:
        raise FileNotFoundError(f"template app not found: {app_id}")
    if not bool(app.get("copyable", True)):
        raise PermissionError(f"template app is not copyable: {app_id}")

    project_path = Path(project_dir).expanduser().resolve()
    app_package = _safe_package_name(str(app.get("id") or app_id))
    source_dir = Path(str(app.get("app_dir") or "")).resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"template source directory not found: {source_dir}")

    agents_dir = _project_agents_dir(project_path)
    agents_dir.mkdir(parents=True, exist_ok=True)
    target_dir = _target_dir_for_app(app_package, project_path)
    try:
        target_dir.relative_to(agents_dir)
    except ValueError as exc:
        raise ValueError(f"target directory escapes project agents directory: {target_dir}") from exc

    if target_dir.exists():
        if not overwrite:
            return _import_existing_claw_app_from_project(app, project_path)
        shutil.rmtree(target_dir)

    shutil.copytree(source_dir, target_dir, ignore=_copy_ignore)
    _cleanup_imported_template_resources(target_dir)

    entry = str(app.get("entry") or app.get("workflow") or "")
    workflow_file = (target_dir / entry).resolve()
    if not workflow_file.is_file():
        raise FileNotFoundError(f"workflow file not found after import: {workflow_file}")

    import_info = _ensure_project_import(
        project_path,
        app_package,
        entry,
        str(app.get("workflow_id") or app.get("id") or app_package),
    )

    return {
        "app": app,
        "project_dir": str(project_path),
        "target_dir": str(target_dir),
        "workflow_file": str(workflow_file),
        "workflow_id": str(app.get("workflow_id") or app.get("id") or app_package),
        **import_info,
    }


def register_project_claw_app_workflow(import_result: dict[str, Any], project: Any) -> Any:
    """Hot-register an imported project template while preserving package context."""
    from agentclaw.api.registry import WorkflowRegistry

    app = import_result.get("app") if isinstance(import_result.get("app"), dict) else {}
    app_id = str(app.get("id") or Path(str(import_result.get("target_dir") or "")).name)
    entry = str(app.get("entry") or app.get("workflow") or "")
    workflow_id = str(import_result.get("workflow_id") or app.get("workflow_id") or app.get("id") or app_id)
    workflow_file = Path(str(import_result.get("workflow_file") or ""))
    module_name = _project_workflow_module_name(app_id, entry)

    project_path = Path(str(import_result.get("project_dir") or getattr(project, "project_dir", ""))).resolve()
    project_path_text = str(project_path)
    inserted_path = False
    if project_path_text not in sys.path:
        sys.path.insert(0, project_path_text)
        inserted_path = True

    try:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)
    finally:
        if inserted_path:
            try:
                sys.path.remove(project_path_text)
            except ValueError:
                pass

    workflow = WorkflowRegistry.get(workflow_id)
    if workflow is None:
        raise RuntimeError(f"workflow '{workflow_id}' was not registered by {workflow_file}")

    setattr(workflow, "is_builtin", False)
    setattr(workflow, "agent_square_app_id", "")
    setattr(workflow, "recommended_input", app.get("recommended_input") or "")
    _attach_project_runtime_config(workflow, project)
    return workflow


def register_claw_app_workflows(app_id: str | None = None) -> dict[str, Any]:
    """Import packaged Claw App workflow modules and register their workflows."""
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.config import get_config

    registered: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    project = get_config().project

    for app in list_claw_apps():
        if app_id and app.get("id") != app_id:
            continue

        workflow_id = str(app.get("workflow_id") or app.get("id") or "")
        workflow_path = Path(str(app.get("workflow_path") or ""))
        if not workflow_id:
            failed.append({"app_id": str(app.get("id", "")), "error": "missing workflow_id"})
            continue
        existing_workflow = WorkflowRegistry.get(workflow_id)
        if existing_workflow:
            _attach_claw_app_metadata(existing_workflow, app)
            _attach_project_runtime_config(existing_workflow, project)
            skipped.append(workflow_id)
            continue
        if not workflow_path.is_file():
            failed.append({"app_id": str(app.get("id", "")), "error": f"workflow file not found: {workflow_path}"})
            continue

        module_name = _workflow_module_name(app)
        try:
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            else:
                importlib.import_module(module_name)
            workflow = WorkflowRegistry.get(workflow_id)
            if workflow is None:
                raise RuntimeError(f"workflow '{workflow_id}' was not registered by {workflow_path}")
            _attach_claw_app_metadata(workflow, app)
            _attach_project_runtime_config(workflow, project)
            registered.append(workflow_id)
        except Exception as exc:
            failed.append({"app_id": str(app.get("id", "")), "error": str(exc)})

    return {
        "registered_workflow_ids": registered,
        "skipped_workflow_ids": skipped,
        "failed_apps": failed,
    }


def _attach_claw_app_metadata(workflow: Any, app: dict[str, Any]) -> None:
    setattr(workflow, "is_builtin", True)
    setattr(workflow, "agent_square_app_id", app.get("id") or "")
    setattr(workflow, "recommended_input", app.get("recommended_input") or "")


def _attach_project_runtime_config(workflow: Any, project: Any) -> None:
    if getattr(project, "models_config", None):
        setattr(workflow, "_models_config", str(project.models_config))
    if getattr(project, "mcp_config", None):
        setattr(workflow, "_mcp_config", str(project.mcp_config))
    if getattr(project, "skills_dir", None):
        setattr(workflow, "_skills_dir", str(project.skills_dir))


__all__ = [
    "AGENT_SQUARE_DIR",
    "_workflow_module_name",
    "get_claw_app",
    "get_claw_app_import_status",
    "import_claw_app_to_project",
    "list_claw_apps",
    "register_project_claw_app_workflow",
    "register_claw_app_workflows",
]
