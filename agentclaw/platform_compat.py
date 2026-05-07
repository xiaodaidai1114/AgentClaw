"""
Platform compatibility helpers.

Keep Windows asyncio and host-runtime compatibility logic in one place.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

_DOCKER_SERVICE_HOST_MAP = {
    "postgres": "127.0.0.1",
    "redis": "127.0.0.1",
}


def apply_windows_selector_event_loop_policy() -> None:
    """Use SelectorEventLoop on Windows for psycopg async compatibility."""
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is None:
        return
    try:
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, policy_cls):
            asyncio.set_event_loop_policy(policy_cls())
    except Exception:
        pass


def apply_windows_proactor_event_loop_policy() -> None:
    """Use ProactorEventLoop on Windows for subprocess-heavy runtimes."""
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_cls is None:
        return
    try:
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, policy_cls):
            asyncio.set_event_loop_policy(policy_cls())
    except Exception:
        pass


def is_windows_proactor_event_loop(loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """Whether the current Windows event loop is an incompatible Proactor loop."""
    if sys.platform != "win32":
        return False
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
    return "proactor" in type(loop).__name__.lower()


async def run_subprocess_in_executor(
    cmd,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    shell: bool = False,
    executable: str | None = None,
) -> subprocess.CompletedProcess:
    """
    Run subprocess.run() in a thread to avoid Windows SelectorEventLoop limitations.

    This is primarily used by tool servers on Windows, where psycopg async prefers
    SelectorEventLoop but asyncio subprocess transports do not work reliably.
    """
    loop = asyncio.get_running_loop()

    def _terminate_process_tree(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return
            except Exception:
                pass
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                return
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass

    def _run() -> subprocess.CompletedProcess:
        proc: subprocess.Popen | None = None
        try:
            popen_kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "cwd": cwd,
                "env": env,
                "executable": executable,
                "shell": shell,
            }
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                if creationflags:
                    popen_kwargs["creationflags"] = creationflags
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                cmd,
                **popen_kwargs,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired as exc:
            if proc is not None:
                _terminate_process_tree(proc)
                try:
                    proc.communicate(timeout=2)
                except Exception:
                    pass
            raise asyncio.TimeoutError from exc

    return await loop.run_in_executor(None, _run)


def running_in_container() -> bool:
    """Best-effort detection for Docker/container runtime."""
    return Path("/.dockerenv").exists() or bool(os.getenv("KUBERNETES_SERVICE_HOST"))


def normalize_service_host(host: str) -> str:
    """Map docker-compose service aliases to localhost when running on host."""
    value = (host or "").strip()
    if not value or running_in_container():
        return value
    return _DOCKER_SERVICE_HOST_MAP.get(value.lower(), value)


def get_service_host_fallback(host: str) -> str | None:
    """Return the localhost fallback for a docker-compose service alias."""
    value = (host or "").strip().lower()
    if not value or running_in_container():
        return None
    return _DOCKER_SERVICE_HOST_MAP.get(value)
