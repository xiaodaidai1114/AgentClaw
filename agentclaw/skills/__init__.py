"""
AgentClaw Skills - Anthropic Skills specification support

Skills are knowledge injection, not tool conversion.
LLM uses code execution tools (python, shell, etc.) via MCP protocol.

When LLMNode uses skills parameter, it automatically starts the built-in
skill-tools MCP server (agentclaw.mcp.builtin_servers) which provides:
- python: Execute Python code/script with skill's venv
- shell: Execute shell commands  
- read_file/write_file/list_files: File operations
"""

from pathlib import Path
from typing import Optional

from .schema import Skill
from .parser import SkillParser
from .manager import SkillManager
from .executor import ScriptExecutor, SkillEnvironment

# Global SkillManager singleton
_global_skill_manager: Optional[SkillManager] = None
_builtin_skill_manager: Optional[SkillManager] = None
_skill_managers_by_dir: dict[str, SkillManager] = {}


def get_skill_manager(skills_dir: Optional[str] = None, auto_init: bool = True) -> Optional[SkillManager]:
    """Get SkillManager instance
    
    Args:
        skills_dir: Skills directory path. If provided, creates a dedicated manager
                    for that path. If None, uses global singleton with default ./skills/
        auto_init: Whether to auto-initialize (load skills and environments)
    
    Returns:
        SkillManager instance, or None if directory doesn't exist
    """
    global _global_skill_manager
    
    if skills_dir:
        # Explicit path: cache manager by directory to avoid duplicate full reloads.
        path = Path(skills_dir).resolve()
        if not path.exists():
            return None
        key = str(path)
        existing = _skill_managers_by_dir.get(key)
        if existing is not None:
            if auto_init:
                # Ensure lazy-loaded managers are initialized when requested.
                existing.list()
            return existing

        manager = SkillManager(str(path), auto_init_env=auto_init)
        if auto_init:
            manager.load_all()
        _skill_managers_by_dir[key] = manager
        return manager
    
    # Default path: use global singleton
    if _global_skill_manager is not None:
        return _global_skill_manager
    
    path = Path("skills")
    if not path.exists():
        return None
    
    _global_skill_manager = SkillManager(str(path), auto_init_env=auto_init)
    if auto_init:
        _global_skill_manager.load_all()
    
    return _global_skill_manager


def get_builtin_skills_dir() -> Path:
    """Get built-in skills directory path."""
    return Path(__file__).resolve().parent / "builtin_skills"


def get_builtin_skill_manager(auto_init: bool = True) -> Optional[SkillManager]:
    """Get built-in SkillManager singleton.

    Built-in skills are shipped with AgentClaw package and are independent
    from project local ``./skills`` directory.

    Args:
        auto_init: Whether to auto-load skills and init environments.

    Returns:
        SkillManager instance, or None if builtin skills directory is missing.
    """
    global _builtin_skill_manager

    if _builtin_skill_manager is not None:
        if auto_init:
            _builtin_skill_manager.list()
        return _builtin_skill_manager

    path = get_builtin_skills_dir()
    if not path.exists():
        return None

    _builtin_skill_manager = SkillManager(str(path), auto_init_env=True)
    if auto_init:
        _builtin_skill_manager.load_all()

    return _builtin_skill_manager


def reset_skill_manager() -> None:
    """Reset global SkillManager (for testing)"""
    global _global_skill_manager, _builtin_skill_manager, _skill_managers_by_dir
    _global_skill_manager = None
    _builtin_skill_manager = None
    _skill_managers_by_dir = {}


__all__ = [
    "Skill",
    "SkillParser",
    "SkillManager",
    "ScriptExecutor",
    "SkillEnvironment",
    "get_skill_manager",
    "get_builtin_skills_dir",
    "get_builtin_skill_manager",
    "reset_skill_manager",
]
