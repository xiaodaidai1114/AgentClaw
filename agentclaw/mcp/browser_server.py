"""
Browser CDP MCP Server — built-in browser automation tools for AgentClaw.

Provides a single `browser` tool with action-based dispatch:
  navigate, snapshot, click, fill, type, hover, drag, select,
  fill_form, scroll_into_view, press, wait, get_text, eval,
  tabs, switch_tab, new_tab, close_tab, close

Core mechanism:
  1. navigate/snapshot returns element refs (e1, e2...) via ariaSnapshot + getByRole
  2. Interact using refs: click ref=e1, fill ref=e2 text="hello"
  3. Each tab has an isolated targetId with cached refs
  4. Supports interactive/compact/maxDepth snapshot modes

Requires: Playwright Python package and a Chromium/Chrome/Edge executable.
Recommended install: uv pip install -e .[all] && playwright install chromium

Usage:
    python -m agentclaw.mcp.browser_server
    python -m agentclaw.mcp.browser_server --cdp-port 9222
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from agentclaw.logger.config import get_logger
from agentclaw.platform_compat import apply_windows_proactor_event_loop_policy

apply_windows_proactor_event_loop_policy()
logger = get_logger(__name__)

# ============ Constants ============
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
MAX_CONNECT_RETRIES = 3
MAX_SNAPSHOT_CHARS = 8000

INTERACTIVE_ROLES = frozenset({
    'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox',
    'listbox', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'option', 'searchbox', 'slider', 'spinbutton', 'switch', 'tab', 'treeitem',
})

CONTENT_ROLES = frozenset({
    'heading', 'cell', 'gridcell', 'columnheader', 'rowheader',
    'listitem', 'article', 'region', 'main', 'navigation',
})

STRUCTURAL_ROLES = frozenset({
    'generic', 'group', 'list', 'table', 'row', 'rowgroup',
    'grid', 'treegrid', 'menu', 'menubar', 'toolbar', 'tablist',
    'tree', 'directory', 'document', 'application', 'presentation', 'none',
})


# ============ Data Structures ============
@dataclass
class RoleRef:
    role: str
    name: Optional[str] = None
    nth: Optional[int] = None


@dataclass
class PageState:
    target_id: str
    role_refs: Dict[str, RoleRef] = field(default_factory=dict)
    role_refs_frame_selector: Optional[str] = None


@dataclass
class ConnectedBrowser:
    browser: Any = None
    cdp_url: str = ""
    playwright: Any = None
    chrome_process: Any = None


# ============ Global State ============
_connection: Optional[ConnectedBrowser] = None
_page_states: Dict[str, PageState] = {}
_current_target_id: Optional[str] = None


def _format_tool_error(err: Exception) -> str:
    msg = str(err).strip()
    if isinstance(err, NotImplementedError) and sys.platform == "win32":
        return (
            "NotImplementedError: browser-tools is likely running under an "
            "incompatible Windows event loop. Restart after updating."
        )
    if isinstance(err, asyncio.TimeoutError):
        timeout_msg = msg or "asyncio.TimeoutError"
        if timeout_msg == "TimeoutError":
            timeout_msg = "asyncio.TimeoutError"
        return f"Timeout: {timeout_msg}"
    if not msg:
        msg = type(err).__name__
        if getattr(err, "__module__", "") == "asyncio.exceptions":
            msg = f"asyncio.{msg}"
    if "timeout" in msg.lower():
        return f"Timeout: {msg}"
    if "connect" in msg.lower():
        return f"Connection failed: {msg}"
    return msg


def _playwright_install_hint() -> str:
    return "Install Playwright: uv pip install -e .[all] && playwright install chromium"


def _should_launch_headless() -> bool:
    raw = os.getenv("BROWSER_HEADLESS", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return sys.platform != "win32"


def _system_browser_hint() -> str:
    if sys.platform == "win32":
        return "Or install/update Google Chrome or Microsoft Edge."
    if sys.platform == "darwin":
        return "Or install/update Google Chrome, Microsoft Edge, or Chromium."
    return "Or install Google Chrome / Chromium from your system package manager."


# ============ Browser Launch & Connect ============
def _find_browser_path() -> Optional[str]:
    """Find system Chrome/Edge/Chromium binary path."""
    import platform
    system = platform.system()
    if system == "Darwin":
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Linux":
        paths = [
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
        ]
    else:
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def _find_playwright_chromium() -> Optional[str]:
    """Find playwright's bundled Chromium binary path."""
    try:
        from playwright._impl._driver import compute_driver_executable
        driver_dir = Path(compute_driver_executable()).parent
        # playwright stores browsers under driver_dir/package/.local-browsers/
        browsers_dir = driver_dir / "package" / ".local-browsers"
        if not browsers_dir.exists():
            return None
        # Find chromium-* directory
        for d in sorted(browsers_dir.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("chromium"):
                # Linux: chrome-linux/chrome, macOS: chrome-mac/Chromium.app/.../Chromium
                chrome_linux = d / "chrome-linux" / "chrome"
                if chrome_linux.exists():
                    return str(chrome_linux)
                chrome_mac = d / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
                if chrome_mac.exists():
                    return str(chrome_mac)
                # Windows
                chrome_win = d / "chrome-win" / "chrome.exe"
                if chrome_win.exists():
                    return str(chrome_win)
    except Exception:
        pass
    return None


def _launch_browser(port: int = CDP_PORT) -> subprocess.Popen:
    """Launch a browser with CDP enabled.
    
    Priority: playwright's bundled Chromium > system Chrome/Edge.
    """
    # Try playwright's bundled Chromium first (most reliable in server environments)
    browser_path = _find_playwright_chromium() or _find_browser_path()
    if not browser_path:
        raise RuntimeError(
            "No browser found. "
            f"{_playwright_install_hint()}\n"
            f"{_system_browser_hint()}"
        )
    user_data_dir = os.path.join(os.path.expanduser("~"), ".agentclaw", "browser-profile")
    os.makedirs(user_data_dir, exist_ok=True)
    args = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run", "--no-default-browser-check", "--disable-sync",
        "--disable-gpu", "--no-sandbox",
        "about:blank",
    ]
    if _should_launch_headless():
        args.insert(3, "--headless=new")
    logger.info(
        "Launching browser-tools browser: path=%s port=%s headless=%s",
        browser_path,
        port,
        _should_launch_headless(),
    )
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("127.0.0.1", port))
                return process
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    process.kill()
    raise RuntimeError(f"Browser CDP port {port} not ready after launch")


async def _connect_browser(cdp_url: str = None) -> ConnectedBrowser:
    """Connect to browser via CDP. Auto-launches if needed (local only)."""
    global _connection
    if cdp_url is None:
        cdp_url = f"http://127.0.0.1:{CDP_PORT}"
    cdp_url = cdp_url.rstrip("/")

    if _connection and _connection.cdp_url == cdp_url and _connection.browser:
        try:
            _ = _connection.browser.contexts
            return _connection
        except Exception:
            _connection = None

    from playwright.async_api import async_playwright
    from urllib.parse import urlparse

    parsed = urlparse(cdp_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or CDP_PORT

    cdp_available = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((host, port))
            cdp_available = True
    except (ConnectionRefusedError, OSError):
        pass

    chrome_process = None
    if not cdp_available:
        is_local = host in ("127.0.0.1", "localhost", "::1")
        if is_local:
            chrome_process = _launch_browser(port)
        else:
            raise RuntimeError(f"Cannot connect to remote CDP: {cdp_url}")

    pw = await async_playwright().start()
    last_err = None
    for attempt in range(MAX_CONNECT_RETRIES):
        try:
            timeout = 5000 + attempt * 2000
            browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=timeout)
            conn = ConnectedBrowser(browser=browser, cdp_url=cdp_url, playwright=pw, chrome_process=chrome_process)
            _connection = conn
            browser.on("disconnected", lambda: _on_disconnect())
            return conn
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.25 + attempt * 0.25)

    await pw.stop()
    raise RuntimeError(
        f"CDP connection failed after {MAX_CONNECT_RETRIES} retries: {last_err}"
    ) from last_err


def _on_disconnect():
    global _connection
    _connection = None


async def _close_browser() -> dict:
    global _connection, _page_states, _current_target_id
    if _connection:
        try:
            if _connection.playwright:
                await _connection.playwright.stop()
        except Exception:
            pass
        _connection = None
    _page_states.clear()
    _current_target_id = None
    return {"closed": True}


# ============ Page / Tab Management ============
async def _get_page_target_id(page) -> Optional[str]:
    try:
        session = await page.context.new_cdp_session(page)
        try:
            info = await session.send("Target.getTargetInfo")
            return info.get("targetInfo", {}).get("targetId", "")
        finally:
            await session.detach()
    except Exception:
        return None


def _ensure_page_state(target_id: str) -> PageState:
    if target_id not in _page_states:
        _page_states[target_id] = PageState(target_id=target_id)
    return _page_states[target_id]


async def _get_page(cdp_url: str = None, target_id: str = None):
    global _current_target_id
    conn = await _connect_browser(cdp_url)
    browser = conn.browser

    contexts = browser.contexts
    if not contexts:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        tid = await _get_page_target_id(page)
        if tid:
            _current_target_id = tid
            _ensure_page_state(tid)
        return page

    pages = []
    for ctx in contexts:
        pages.extend(ctx.pages)

    if not pages:
        page = await contexts[0].new_page()
        tid = await _get_page_target_id(page)
        if tid:
            _current_target_id = tid
            _ensure_page_state(tid)
        return page

    if target_id:
        for page in pages:
            tid = await _get_page_target_id(page)
            if tid == target_id:
                _current_target_id = target_id
                return page
        if len(pages) == 1:
            return pages[0]
        raise ValueError(f"Tab {target_id} not found")

    if _current_target_id:
        for page in pages:
            tid = await _get_page_target_id(page)
            if tid == _current_target_id:
                return page

    page = pages[-1]
    tid = await _get_page_target_id(page)
    if tid:
        _current_target_id = tid
    return page


async def _list_tabs(cdp_url: str = None) -> List[Dict[str, Any]]:
    conn = await _connect_browser(cdp_url)
    tabs = []
    for ctx in conn.browser.contexts:
        for page in ctx.pages:
            try:
                tid = await _get_page_target_id(page)
                tabs.append({
                    "targetId": tid or "",
                    "url": page.url,
                    "title": await page.title(),
                    "active": tid == _current_target_id,
                })
            except Exception:
                pass
    return tabs


async def _switch_tab(target_id: str = None, index: int = None, cdp_url: str = None) -> dict:
    global _current_target_id
    conn = await _connect_browser(cdp_url)
    pages = []
    for ctx in conn.browser.contexts:
        pages.extend(ctx.pages)

    if target_id:
        for page in pages:
            tid = await _get_page_target_id(page)
            if tid == target_id:
                _current_target_id = target_id
                await page.bring_to_front()
                return {"targetId": target_id, "url": page.url, "title": await page.title()}
        raise ValueError(f"Tab {target_id} not found")

    if index is not None:
        if 0 <= index < len(pages):
            page = pages[index]
            tid = await _get_page_target_id(page)
            _current_target_id = tid
            await page.bring_to_front()
            return {"targetId": tid, "url": page.url, "title": await page.title()}
        raise ValueError(f"Tab index {index} out of range (total {len(pages)})")

    raise ValueError("Need target_id or index")


async def _new_tab(url: str = "about:blank", cdp_url: str = None) -> dict:
    global _current_target_id
    conn = await _connect_browser(cdp_url)
    ctx = conn.browser.contexts[0] if conn.browser.contexts else await conn.browser.new_context()
    page = await ctx.new_page()
    if url != "about:blank":
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    tid = await _get_page_target_id(page)
    _current_target_id = tid
    return {"targetId": tid, "url": page.url, "title": await page.title()}


async def _close_tab(target_id: str = None, cdp_url: str = None) -> dict:
    global _current_target_id
    page = await _get_page(cdp_url, target_id)
    url = page.url
    await page.close()
    if target_id == _current_target_id:
        _current_target_id = None
        _page_states.pop(target_id, None)
    return {"closed": True, "url": url}


# ============ Ref Locator ============
def _ref_locator(page, ref: str, state: PageState = None):
    """Convert ref (e1, e2...) to Playwright locator via getByRole."""
    normalized = ref
    if ref.startswith("@"):
        normalized = ref[1:]
    elif ref.startswith("ref="):
        normalized = ref[4:]

    if not re.match(r"^e\d+$", normalized):
        frame_sel = state.role_refs_frame_selector if state else None
        if frame_sel:
            return page.frame_locator(frame_sel).locator(ref)
        return page.locator(ref)

    if not state or not state.role_refs:
        raise ValueError(f"Unknown ref '{normalized}'. Run snapshot first to get element refs.")

    role_ref = state.role_refs.get(normalized)
    if not role_ref:
        raise ValueError(f"Unknown ref '{normalized}'. Run snapshot first to get element refs.")

    scope = (page.frame_locator(state.role_refs_frame_selector)
             if state.role_refs_frame_selector else page)

    if role_ref.name:
        locator = scope.get_by_role(role_ref.role, name=role_ref.name, exact=True)
    else:
        locator = scope.get_by_role(role_ref.role)

    if role_ref.nth is not None:
        locator = locator.nth(role_ref.nth)

    return locator


# ============ Snapshot ============
class _RoleNameTracker:
    def __init__(self):
        self.counts: Dict[str, int] = {}
        self.refs_by_key: Dict[str, List[str]] = {}

    def get_key(self, role: str, name: Optional[str] = None) -> str:
        return f"{role}:{name or ''}"

    def get_next_index(self, role: str, name: Optional[str] = None) -> int:
        key = self.get_key(role, name)
        current = self.counts.get(key, 0)
        self.counts[key] = current + 1
        return current

    def track_ref(self, role: str, name: Optional[str], ref: str):
        key = self.get_key(role, name)
        self.refs_by_key.setdefault(key, []).append(ref)

    def get_duplicate_keys(self) -> set:
        return {key for key, refs in self.refs_by_key.items() if len(refs) > 1}


def _build_role_snapshot(
    aria_snapshot: str,
    interactive: bool = False,
    compact: bool = False,
    max_depth: Optional[int] = None,
) -> Tuple[str, Dict[str, RoleRef]]:
    lines = aria_snapshot.split("\n")
    refs: Dict[str, RoleRef] = {}
    tracker = _RoleNameTracker()
    counter = [0]

    def next_ref() -> str:
        counter[0] += 1
        return f"e{counter[0]}"

    def get_indent_level(line: str) -> int:
        match = re.match(r"^(\s*)", line)
        return len(match.group(1)) // 2 if match else 0

    if interactive:
        result = []
        for line in lines:
            depth = get_indent_level(line)
            if max_depth is not None and depth > max_depth:
                continue
            match = re.match(r"^(\s*-\s*)(\w+)(?:\s+\"([^\"]*)\")?(.*)$", line)
            if not match:
                continue
            prefix, role_raw, name, suffix = match.groups()
            if role_raw.startswith("/"):
                continue
            role = role_raw.lower()
            if role not in INTERACTIVE_ROLES:
                continue
            ref = next_ref()
            nth = tracker.get_next_index(role, name)
            tracker.track_ref(role, name, ref)
            refs[ref] = RoleRef(role=role, name=name, nth=nth)
            enhanced = f"- {role_raw}"
            if name:
                enhanced += f' "{name}"'
            enhanced += f" [ref={ref}]"
            if nth > 0:
                enhanced += f" [nth={nth}]"
            result.append(enhanced)
        _remove_nth_from_non_duplicates(refs, tracker)
        return ("\n".join(result) or "(no interactive elements)", refs)

    # Full mode
    result = []
    for line in lines:
        depth = get_indent_level(line)
        if max_depth is not None and depth > max_depth:
            continue
        match = re.match(r"^(\s*-\s*)(\w+)(?:\s+\"([^\"]*)\")?(.*)$", line)
        if not match:
            if not interactive:
                result.append(line)
            continue
        prefix, role_raw, name, suffix = match.groups()
        if role_raw.startswith("/"):
            result.append(line)
            continue
        role = role_raw.lower()
        is_interactive = role in INTERACTIVE_ROLES
        is_content = role in CONTENT_ROLES
        is_structural = role in STRUCTURAL_ROLES
        if compact and is_structural and not name:
            continue
        should_have_ref = is_interactive or (is_content and name)
        if not should_have_ref:
            result.append(line)
            continue
        ref = next_ref()
        nth = tracker.get_next_index(role, name)
        tracker.track_ref(role, name, ref)
        refs[ref] = RoleRef(role=role, name=name, nth=nth)
        enhanced = f"{prefix}{role_raw}"
        if name:
            enhanced += f' "{name}"'
        enhanced += f" [ref={ref}]"
        if nth > 0:
            enhanced += f" [nth={nth}]"
        if suffix:
            enhanced += suffix
        result.append(enhanced)

    _remove_nth_from_non_duplicates(refs, tracker)
    tree = "\n".join(result) or "(empty page)"
    return (tree, refs)


def _remove_nth_from_non_duplicates(refs: Dict[str, RoleRef], tracker: _RoleNameTracker):
    duplicates = tracker.get_duplicate_keys()
    for ref_key, role_ref in refs.items():
        key = tracker.get_key(role_ref.role, role_ref.name)
        if key not in duplicates:
            role_ref.nth = None


# ============ Snapshot Retrieval ============
async def _get_snapshot(
    page, frame_selector: str = None,
    interactive: bool = False, compact: bool = False,
    max_depth: int = None, target_id: str = None,
) -> Dict[str, Any]:
    if frame_selector:
        locator = page.frame_locator(frame_selector).locator(":root")
    else:
        locator = page.locator(":root")

    aria_snapshot = None
    try:
        aria_snapshot = await locator.aria_snapshot()
    except Exception as e:
        logger.debug("browser snapshot aria_snapshot failed: %s", e, exc_info=True)

    if not aria_snapshot:
        return {"snapshot": "(unable to get page snapshot)", "refs": {}, "stats": {}}

    snapshot_text, refs = _build_role_snapshot(
        aria_snapshot, interactive=interactive, compact=compact, max_depth=max_depth,
    )

    # Auto-switch to interactive mode if output too large
    if not interactive and len(snapshot_text) > MAX_SNAPSHOT_CHARS:
        snapshot_text, refs = _build_role_snapshot(
            aria_snapshot, interactive=True, compact=compact, max_depth=max_depth,
        )

    # Store refs
    if target_id:
        state = _ensure_page_state(target_id)
        state.role_refs = refs
        state.role_refs_frame_selector = frame_selector

    interactive_count = sum(1 for r in refs.values() if r.role in INTERACTIVE_ROLES)
    stats = {"refs": len(refs), "interactive": interactive_count}

    # Truncate if still too large
    if len(snapshot_text) > MAX_SNAPSHOT_CHARS:
        snapshot_text = snapshot_text[:MAX_SNAPSHOT_CHARS] + f"\n\n... (truncated, {len(snapshot_text)} chars total)"

    return {"snapshot": snapshot_text, "refs": refs, "stats": stats}


# ============ Interaction Helpers ============
def _normalize_timeout(timeout_ms: Optional[int], default: int = 8000) -> int:
    if timeout_ms is None:
        return default
    return max(500, min(60000, int(timeout_ms)))


def _friendly_error(err: Exception, ref: str) -> str:
    msg = str(err)
    if "Timeout" in msg:
        return f"Element {ref} timed out. It may not be visible. Run snapshot to check."
    if "strict mode violation" in msg.lower():
        return f"Element {ref} matched multiple results. Run snapshot for a more precise ref."
    return f"Operation on {ref} failed: {msg}"


# ============ Core Actions ============
async def _navigate(url: str, cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    tid = await _get_page_target_id(page)
    cdp = cdp_url or f"http://127.0.0.1:{CDP_PORT}"
    snap = await _get_snapshot(page, target_id=tid)
    result = {"url": page.url, "title": await page.title(), "targetId": tid, "snapshot": snap["snapshot"]}
    return result


async def _click_locator_with_fallback(locator, click_opts: Dict[str, Any], double_click: bool = False) -> None:
    try:
        if double_click:
            await locator.dblclick(**click_opts)
        else:
            await locator.click(**click_opts)
    except Exception as e:
        if double_click or "intercepts pointer events" not in str(e).lower():
            raise
        retry_opts = dict(click_opts)
        retry_opts["force"] = True
        logger.info("Retrying browser click with force=True due to intercepted pointer events")
        await locator.click(**retry_opts)


async def _click(ref: str, double_click: bool = False, button: str = "left",
                 modifiers: List[str] = None, timeout_ms: int = None,
                 cdp_url: str = None, target_id: str = None) -> dict:
    global _current_target_id
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    cdp = cdp_url or f"http://127.0.0.1:{CDP_PORT}"
    state = _page_states.get(tid) if tid else None

    old_url = page.url
    new_page_holder = [None]

    def on_page(p):
        new_page_holder[0] = p
    page.context.on("page", on_page)

    try:
        locator = _ref_locator(page, ref, state)
        timeout = _normalize_timeout(timeout_ms)
        click_opts = {"timeout": timeout}
        if button != "left":
            click_opts["button"] = button
        if modifiers:
            click_opts["modifiers"] = modifiers

        await _click_locator_with_fallback(locator, click_opts, double_click=double_click)

        await asyncio.sleep(0.5)
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        result = {"clicked": ref, "targetId": tid}

        new_page = new_page_holder[0]
        if new_page:
            try:
                await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            new_tid = await _get_page_target_id(new_page)
            _current_target_id = new_tid
            result["new_tab"] = True
            result["new_targetId"] = new_tid
            result["new_url"] = new_page.url
            snap = await _get_snapshot(new_page, target_id=new_tid)
            result["snapshot"] = snap["snapshot"]
        elif page.url != old_url:
            result["new_url"] = page.url
            snap = await _get_snapshot(page, target_id=tid)
            result["snapshot"] = snap["snapshot"]

        return result
    except Exception as e:
        raise RuntimeError(_friendly_error(e, ref))
    finally:
        page.context.remove_listener("page", on_page)


async def _fill(ref: str, text: str, submit: bool = False, slowly: bool = False,
                timeout_ms: int = None, cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    locator = _ref_locator(page, ref, state)
    timeout = _normalize_timeout(timeout_ms)
    try:
        if slowly:
            await locator.click(timeout=timeout)
            await locator.type(text, delay=75)
        else:
            await locator.fill(text, timeout=timeout)
        if submit:
            await locator.press("Enter", timeout=timeout)
        return {"filled": ref, "text": text, "submitted": submit}
    except Exception as e:
        raise RuntimeError(_friendly_error(e, ref))


async def _hover(ref: str, timeout_ms: int = None, cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    locator = _ref_locator(page, ref, state)
    try:
        await locator.hover(timeout=_normalize_timeout(timeout_ms))
        return {"hovered": ref}
    except Exception as e:
        raise RuntimeError(_friendly_error(e, ref))


async def _drag(start_ref: str, end_ref: str, timeout_ms: int = None,
                cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    try:
        start_loc = _ref_locator(page, start_ref, state)
        end_loc = _ref_locator(page, end_ref, state)
        await start_loc.drag_to(end_loc, timeout=_normalize_timeout(timeout_ms))
        return {"dragged": f"{start_ref} -> {end_ref}"}
    except Exception as e:
        raise RuntimeError(_friendly_error(e, f"{start_ref}->{end_ref}"))


async def _select_option(ref: str, values: List[str], timeout_ms: int = None,
                         cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    locator = _ref_locator(page, ref, state)
    try:
        await locator.select_option(values, timeout=_normalize_timeout(timeout_ms))
        return {"selected": ref, "values": values}
    except Exception as e:
        raise RuntimeError(_friendly_error(e, ref))


async def _fill_form(fields: List[Dict[str, Any]], timeout_ms: int = None,
                     cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    timeout = _normalize_timeout(timeout_ms)
    filled = []
    for f in fields:
        ref = f.get("ref", "").strip()
        field_type = f.get("type", "text").strip()
        value = f.get("value", "")
        if not ref:
            continue
        locator = _ref_locator(page, ref, state)
        try:
            if field_type in ("checkbox", "radio"):
                checked = value in (True, 1, "1", "true")
                await locator.set_checked(checked, timeout=timeout)
            else:
                await locator.fill(str(value), timeout=timeout)
            filled.append(ref)
        except Exception as e:
            raise RuntimeError(_friendly_error(e, ref))
    return {"filled_fields": filled, "count": len(filled)}


async def _scroll_into_view(ref: str, timeout_ms: int = None,
                            cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    locator = _ref_locator(page, ref, state)
    try:
        await locator.scroll_into_view_if_needed(timeout=_normalize_timeout(timeout_ms, 20000))
        return {"scrolled_to": ref}
    except Exception as e:
        raise RuntimeError(_friendly_error(e, ref))


async def _press(key: str, cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    await page.keyboard.press(key)
    return {"pressed": key}


async def _wait_for(ref: str = None, text: str = None, text_gone: str = None,
                    selector: str = None, url: str = None,
                    load_state: str = None, time_ms: int = None,
                    timeout_ms: int = None,
                    cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    timeout = _normalize_timeout(timeout_ms, 20000)
    if time_ms is not None:
        await page.wait_for_timeout(max(0, time_ms))
    if text:
        await page.get_by_text(text).first.wait_for(state="visible", timeout=timeout)
    if text_gone:
        await page.get_by_text(text_gone).first.wait_for(state="hidden", timeout=timeout)
    if selector:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
    if url:
        await page.wait_for_url(url, timeout=timeout)
    if load_state:
        await page.wait_for_load_state(load_state, timeout=timeout)
    if ref:
        tid = target_id or _current_target_id
        state = _page_states.get(tid) if tid else None
        locator = _ref_locator(page, ref, state)
        await locator.wait_for(timeout=timeout)
    return {"waited": True}


async def _get_text(ref: str, cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = target_id or _current_target_id
    state = _page_states.get(tid) if tid else None
    locator = _ref_locator(page, ref, state)
    text = await locator.text_content(timeout=5000)
    return {"ref": ref, "text": text}


async def _evaluate(script: str, ref: str = None,
                    cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    if ref:
        tid = target_id or _current_target_id
        state = _page_states.get(tid) if tid else None
        locator = _ref_locator(page, ref, state)
        result = await locator.evaluate(script)
    else:
        result = await page.evaluate(script)
    return {"result": result}


async def _get_page_info(cdp_url: str = None, target_id: str = None) -> dict:
    page = await _get_page(cdp_url, target_id)
    tid = await _get_page_target_id(page)
    return {"url": page.url, "title": await page.title(), "targetId": tid}


# ============ Unified Async Handler ============
async def browser_handler(params: dict) -> str:
    """Main handler — dispatches action to the appropriate function. Returns text output."""
    action = params.get("action", "")
    if not action:
        raise ValueError("Missing 'action' parameter")

    cdp_url = params.get("cdp_url")
    target_id = params.get("target_id")

    if action == "navigate":
        url = params.get("url", "")
        if not url:
            raise ValueError("Missing 'url'")
        r = await _navigate(url, cdp_url=cdp_url, target_id=target_id)
        out = f"Opened: {r['url']}\nTitle: {r['title']}\ntargetId: {r.get('targetId', '')}"
        if r.get("snapshot"):
            out += f"\n\n{r['snapshot']}"
        return out

    elif action in ("snapshot", "elements"):
        page = await _get_page(cdp_url, target_id)
        tid = target_id or _current_target_id
        snap = await _get_snapshot(
            page,
            frame_selector=params.get("frame") or None,
            interactive=params.get("interactive", False),
            compact=params.get("compact", False),
            max_depth=params.get("max_depth"),
            target_id=tid,
        )
        out = f"URL: {page.url}\nTitle: {await page.title()}\ntargetId: {tid}"
        s = snap.get("stats", {})
        if s:
            out += f"\n[refs={s.get('refs', 0)}, interactive={s.get('interactive', 0)}]"
        out += f"\n\n{snap['snapshot']}"
        return out

    elif action == "click":
        ref = params.get("ref", "")
        if not ref:
            raise ValueError("Missing 'ref'")
        r = await _click(
            ref, double_click=params.get("double_click", False),
            button=params.get("button", "left"),
            modifiers=params.get("modifiers"),
            timeout_ms=params.get("timeout"),
            cdp_url=cdp_url, target_id=target_id,
        )
        out = f"Clicked: {ref}"
        if r.get("new_tab"):
            out += f"\nNew tab: {r['new_url']} (targetId: {r.get('new_targetId', '')})"
        elif r.get("new_url"):
            out += f"\nNavigated: {r['new_url']}"
        if r.get("snapshot"):
            out += f"\n\n{r['snapshot']}"
        return out

    elif action == "fill":
        ref = params.get("ref", "")
        text = params.get("text", "") or params.get("value", "")
        if not ref:
            raise ValueError("Missing 'ref'")
        if not text:
            raise ValueError("Missing 'text'")
        r = await _fill(
            ref, text, submit=params.get("submit", False),
            slowly=params.get("slowly", False),
            timeout_ms=params.get("timeout"),
            cdp_url=cdp_url, target_id=target_id,
        )
        out = f"Filled {ref}: {text}"
        if r.get("submitted"):
            out += " (submitted)"
        return out

    elif action == "type":
        ref = params.get("ref", "")
        text = params.get("text", "")
        if not ref:
            raise ValueError("Missing 'ref'")
        await _fill(ref, text, slowly=True, submit=params.get("submit", False),
                    timeout_ms=params.get("timeout"), cdp_url=cdp_url, target_id=target_id)
        return f"Typed {ref}: {text}"

    elif action == "hover":
        ref = params.get("ref", "")
        if not ref:
            raise ValueError("Missing 'ref'")
        await _hover(ref, timeout_ms=params.get("timeout"), cdp_url=cdp_url, target_id=target_id)
        return f"Hovered: {ref}"

    elif action == "drag":
        start_ref = params.get("start_ref", "")
        end_ref = params.get("end_ref", "")
        if not start_ref or not end_ref:
            raise ValueError("Missing 'start_ref' or 'end_ref'")
        await _drag(start_ref, end_ref, timeout_ms=params.get("timeout"),
                    cdp_url=cdp_url, target_id=target_id)
        return f"Dragged: {start_ref} -> {end_ref}"

    elif action == "select":
        ref = params.get("ref", "")
        values = params.get("values", [])
        if not ref or not values:
            raise ValueError("Missing 'ref' or 'values'")
        await _select_option(ref, values, timeout_ms=params.get("timeout"),
                             cdp_url=cdp_url, target_id=target_id)
        return f"Selected {ref}: {values}"

    elif action == "fill_form":
        fields = params.get("fields", [])
        if not fields:
            raise ValueError("Missing 'fields'")
        r = await _fill_form(fields, timeout_ms=params.get("timeout"),
                             cdp_url=cdp_url, target_id=target_id)
        return f"Filled {r['count']} fields: {r['filled_fields']}"

    elif action == "scroll_into_view":
        ref = params.get("ref", "")
        if not ref:
            raise ValueError("Missing 'ref'")
        await _scroll_into_view(ref, timeout_ms=params.get("timeout"),
                                cdp_url=cdp_url, target_id=target_id)
        return f"Scrolled to: {ref}"

    elif action == "press":
        key = params.get("key", "Enter")
        await _press(key, cdp_url=cdp_url, target_id=target_id)
        return f"Pressed: {key}"

    elif action == "wait":
        await _wait_for(
            ref=params.get("ref"), text=params.get("text"),
            text_gone=params.get("text_gone"), selector=params.get("selector"),
            url=params.get("url"), load_state=params.get("load_state"),
            time_ms=params.get("time_ms"), timeout_ms=params.get("timeout"),
            cdp_url=cdp_url, target_id=target_id,
        )
        return "Wait completed"

    elif action == "get_text":
        ref = params.get("ref", "")
        if not ref:
            raise ValueError("Missing 'ref'")
        r = await _get_text(ref, cdp_url=cdp_url, target_id=target_id)
        return f"Text: {r['text']}"

    elif action == "eval":
        script = params.get("script", "")
        if not script:
            raise ValueError("Missing 'script'")
        r = await _evaluate(script, ref=params.get("ref"),
                            cdp_url=cdp_url, target_id=target_id)
        return f"Result: {r['result']}"

    elif action == "info":
        r = await _get_page_info(cdp_url=cdp_url, target_id=target_id)
        return f"URL: {r['url']}\nTitle: {r['title']}\ntargetId: {r.get('targetId', '')}"

    elif action == "tabs":
        tabs = await _list_tabs(cdp_url=cdp_url)
        if not tabs:
            return "No open tabs"
        lines = ["Tabs:"]
        for i, tab in enumerate(tabs):
            active = " [active]" if tab["active"] else ""
            lines.append(f"  {i}: {tab['title'][:50]} - {tab['url'][:60]}{active}")
            lines.append(f"     targetId: {tab['targetId']}")
        return "\n".join(lines)

    elif action == "switch_tab":
        tid = params.get("target_id")
        index = params.get("index")
        if tid is None and index is None:
            raise ValueError("Need 'target_id' or 'index'")
        r = await _switch_tab(target_id=tid, index=int(index) if index is not None else None,
                              cdp_url=cdp_url)
        page = await _get_page(cdp_url, r["targetId"])
        snap = await _get_snapshot(page, target_id=r["targetId"])
        out = f"Switched to: {r['title']}\nURL: {r['url']}\ntargetId: {r['targetId']}"
        out += f"\n\n{snap['snapshot']}"
        return out

    elif action == "new_tab":
        url = params.get("url", "about:blank")
        r = await _new_tab(url, cdp_url=cdp_url)
        return f"New tab: {r['url']}\ntargetId: {r['targetId']}"

    elif action == "close_tab":
        tid = params.get("target_id") or target_id
        r = await _close_tab(target_id=tid, cdp_url=cdp_url)
        return f"Closed tab: {r['url']}"

    elif action == "close":
        await _close_browser()
        return "Browser connection closed"

    else:
        raise ValueError(f"Unknown action: {action}")


# ============ MCP Server ============
TOOL_DESCRIPTION = """Browser automation via CDP (Chrome DevTools Protocol).

Core mechanism:
1. navigate/snapshot returns element refs (e1, e2...) via getByRole
2. Interact using refs: click ref=e1, fill ref=e2 text="hello"
3. Each tab has an isolated targetId with cached refs
4. Supports interactive/compact/maxDepth snapshot modes

Actions:
- navigate: Open URL, returns page snapshot with element refs
- snapshot: Get current page snapshot and element refs
- click: Click element by ref (supports double_click, right-click, modifiers)
- fill: Fill input field (supports submit, slowly)
- type: Type text character by character (slowly)
- hover: Hover over element
- drag: Drag element from start_ref to end_ref
- select: Select dropdown option(s)
- fill_form: Batch fill multiple form fields
- scroll_into_view: Scroll element into viewport
- press: Press keyboard key (Enter, Tab, Escape, etc.)
- wait: Wait for condition (time_ms, text, text_gone, load_state, url)
- get_text: Get element text content
- eval: Execute JavaScript on page or element
- info: Get current page URL, title, targetId
- tabs: List all open tabs
- switch_tab: Switch to tab by targetId or index
- new_tab: Open new tab
- close_tab: Close tab
- close: Close browser connection"""

TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "Action to perform",
            "enum": [
                "navigate", "snapshot", "click", "fill", "type",
                "hover", "drag", "select", "fill_form",
                "scroll_into_view", "press", "wait",
                "get_text", "eval", "info", "tabs",
                "switch_tab", "new_tab", "close_tab", "close",
            ],
        },
        "url": {"type": "string", "description": "URL (navigate/new_tab)"},
        "ref": {"type": "string", "description": "Element ref e.g. e1, e2 (click/fill/hover/etc.)"},
        "text": {"type": "string", "description": "Text content (fill/type)"},
        "key": {"type": "string", "description": "Key name (press), e.g. Enter, Tab, Escape"},
        "frame": {"type": "string", "description": "iframe selector (snapshot)"},
        "interactive": {"type": "boolean", "description": "Only interactive elements (snapshot)"},
        "compact": {"type": "boolean", "description": "Compact mode (snapshot)"},
        "max_depth": {"type": "integer", "description": "Max tree depth (snapshot)"},
        "submit": {"type": "boolean", "description": "Press Enter after fill (fill)"},
        "slowly": {"type": "boolean", "description": "Type character by character (fill)"},
        "double_click": {"type": "boolean", "description": "Double click (click)"},
        "button": {"type": "string", "description": "Mouse button: left/right/middle (click)"},
        "modifiers": {"type": "array", "items": {"type": "string"}, "description": "Modifier keys: Alt/Control/Shift (click)"},
        "start_ref": {"type": "string", "description": "Drag start ref (drag)"},
        "end_ref": {"type": "string", "description": "Drag end ref (drag)"},
        "values": {"type": "array", "items": {"type": "string"}, "description": "Option values (select)"},
        "fields": {
            "type": "array",
            "items": {"type": "object", "properties": {"ref": {"type": "string"}, "type": {"type": "string"}, "value": {}}},
            "description": "Form fields [{ref, type, value}] (fill_form)",
        },
        "text_gone": {"type": "string", "description": "Wait for text to disappear (wait)"},
        "load_state": {"type": "string", "description": "Wait for load state (wait)"},
        "time_ms": {"type": "integer", "description": "Wait milliseconds (wait)"},
        "target_id": {"type": "string", "description": "Tab targetId"},
        "cdp_url": {"type": "string", "description": "CDP URL for remote connection"},
        "index": {"type": "integer", "description": "Tab index (switch_tab)"},
        "timeout": {"type": "integer", "description": "Timeout in ms"},
        "script": {"type": "string", "description": "JavaScript code (eval)"},
    },
    "required": ["action"],
}


class BrowserToolsServer:
    """
    Browser automation MCP server.

    Provides a single `browser` tool with action-based dispatch.
    Requires: Playwright Python package and a Chromium/Chrome/Edge executable.

    Usage:
        python -m agentclaw.mcp.browser_server
        python -m agentclaw.mcp.browser_server --cdp-port 9222
    """

    def __init__(self, cdp_port: int = CDP_PORT):
        global CDP_PORT
        CDP_PORT = cdp_port

        try:
            from mcp.server import Server
            from mcp.types import Tool as MCPTool, TextContent
        except ImportError:
            raise ImportError("MCP SDK required: pip install mcp")

        self._server = Server("browser-tools")
        self._MCPTool = MCPTool
        self._TextContent = TextContent
        self._setup_handlers()

    def _setup_handlers(self):
        MCPTool = self._MCPTool
        TextContent = self._TextContent
        server = self._server

        @server.list_tools()
        async def list_tools():
            return [
                MCPTool(
                    name="browser",
                    description=TOOL_DESCRIPTION,
                    inputSchema=TOOL_INPUT_SCHEMA,
                )
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            if name != "browser":
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
            try:
                output = await browser_handler(arguments)
                return [TextContent(type="text", text=output)]
            except Exception as e:
                logger.exception(
                    "browser-tools call failed: action=%s arguments=%s",
                    arguments.get("action"),
                    arguments,
                )
                error_msg = _format_tool_error(e)
                return [TextContent(type="text", text=f"Error: {error_msg}")]

    async def run(self):
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read, write):
            await self._server.run(read, write, self._server.create_initialization_options())


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Browser Tools MCP Server")
    parser.add_argument("--cdp-port", type=int, default=CDP_PORT, help=f"CDP port (default: {CDP_PORT})")
    args = parser.parse_args()

    server = BrowserToolsServer(cdp_port=args.cdp_port)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
