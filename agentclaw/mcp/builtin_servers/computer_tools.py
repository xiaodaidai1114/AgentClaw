"""Built-in MCP server: computer-tools."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

class ComputerToolsServer:
    """
    Computer Tools MCP Server

    提供截图和系统模拟操作工具：
    - screenshot: 截取屏幕截图
    - mouse_click: 鼠标点击
    - mouse_move: 鼠标移动
    - keyboard_type: 键盘输入文本
    - keyboard_key: 按键/组合键
    - get_screen_size: 获取屏幕尺寸
    - get_windows_elements: Windows 上获取当前桌面窗口/控件树

    Windows 依赖: PowerShell + User32（系统内置），pywinauto（窗口元素枚举）
    Linux 依赖: scrot, xdotool
    macOS 依赖: screencapture (内置), cliclick (可选)

    Usage:
        python -m agentclaw.mcp.builtin_servers computer-tools --working-dir .
    """

    def __init__(self, working_dir: Optional[str] = None, models_config: Optional[str] = None):
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self.models_config = Path(models_config) if models_config else None
        self._screenshot_dir = self.working_dir / ".screenshots"
        self._server = Server("computer-tools")
        self._platform = sys.platform
        self._vl_client = None
        self._setup_handlers()

    def _build_tools(self) -> List[Tool]:
        tools = [
            Tool(
                name="screenshot",
                description=(
                    "Take a screenshot of the entire screen or a specific region. "
                    "Returns the file path of the saved PNG image. "
                    "Omit region for full screen. If region.width or region.height is missing, 0, or negative, "
                    "the tool captures the full screen instead of creating an invalid zero-size image."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "object",
                            "description": (
                                "Optional crop region. Use positive width and height to crop. "
                                "x/y default to 0. Omit region, or pass width/height <= 0, to capture full screen."
                            ),
                            "properties": {
                                "x": {"type": "integer", "default": 0, "description": "Left coordinate. Defaults to 0."},
                                "y": {"type": "integer", "default": 0, "description": "Top coordinate. Defaults to 0."},
                                "width": {"type": "integer", "default": 0, "description": "Crop width. Use a positive value; 0 means full screen."},
                                "height": {"type": "integer", "default": 0, "description": "Crop height. Use a positive value; 0 means full screen."},
                            },
                        },
                        "filename": {
                            "type": "string",
                            "description": "Optional filename, path ignored. .png is added automatically when omitted. Default: screenshot_<timestamp>.png",
                        },
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Optional vision prompt. Fill this only when you need to read or understand the screenshot contents. "
                                "Leave empty/omit when you only need to save the screenshot file, because analysis calls the configured vision model."
                            ),
                        },
                    },
                },
            ),
            Tool(
                name="mouse_click",
                description="Click the mouse at the specified screen coordinates.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                        "button": {
                            "type": "string",
                            "enum": ["left", "right", "middle"],
                            "description": "Mouse button (default: left)",
                        },
                        "clicks": {
                            "type": "integer",
                            "description": "Number of clicks (default: 1, use 2 for double-click)",
                        },
                    },
                    "required": ["x", "y"],
                },
            ),
            Tool(
                name="mouse_move",
                description="Move the mouse cursor to the specified screen coordinates.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                    },
                    "required": ["x", "y"],
                },
            ),
            Tool(
                name="keyboard_type",
                description="Type text string using keyboard simulation.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to type"},
                        "delay": {"type": "integer", "description": "Delay between keystrokes in ms (default: 12)"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="keyboard_key",
                description="Press a key or key combination (e.g. 'Return', 'ctrl+c', 'alt+Tab', 'super').",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key or combo: 'Return', 'ctrl+a', 'alt+F4', 'super', 'Tab', 'Escape', etc.",
                        },
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="get_screen_size",
                description="Get the screen resolution (width x height).",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
        if self._platform == "win32":
            tools.append(
                Tool(
                    name="get_windows_elements",
                    description=(
                        "Windows-only operating system inspection tool. Use pywinauto to list visible desktop windows "
                        "and optionally their child UI elements, including title, class, automation id, handle, process id, "
                        "visibility/enabled state, and screen rectangle. Use this before OS-level mouse/keyboard actions "
                        "when you need stable UI targets."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "backend": {
                                "type": "string",
                                "enum": ["uia", "win32"],
                                "default": "uia",
                                "description": "pywinauto backend. Use 'uia' for modern UI Automation controls; use 'win32' for classic Win32 apps.",
                            },
                            "max_depth": {
                                "type": "integer",
                                "default": 3,
                                "description": "Maximum child-control traversal depth, 0 for top-level windows only.",
                            },
                            "max_windows": {
                                "type": "integer",
                                "default": 20,
                                "description": "Maximum number of top-level windows to return.",
                            },
                            "max_children_per_element": {
                                "type": "integer",
                                "default": 80,
                                "description": "Maximum number of child controls returned per element.",
                            },
                            "visible_only": {
                                "type": "boolean",
                                "default": True,
                                "description": "Return only visible top-level windows when true.",
                            },
                            "include_children": {
                                "type": "boolean",
                                "default": True,
                                "description": "Include child UI elements when true.",
                            },
                        },
                    },
                )
            )
        return tools

    def _setup_handlers(self):
        @self._server.list_tools()
        async def list_tools() -> List[Tool]:
            return self._build_tools()

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            handlers = {
                "screenshot": self._screenshot,
                "mouse_click": self._mouse_click,
                "mouse_move": self._mouse_move,
                "keyboard_type": self._keyboard_type,
                "keyboard_key": self._keyboard_key,
                "get_screen_size": self._get_screen_size,
                "get_windows_elements": self._get_windows_elements,
            }
            handler = handlers.get(name)
            if not handler:
                return [TextContent(type="text", text=f"[ERROR] Unknown tool: {name}")]
            try:
                result = await handler(arguments)
            except Exception as e:
                result = f"[ERROR] {name} failed: {e}"
            return [TextContent(type="text", text=result)]

    async def _run_cmd(self, cmd: List[str], timeout: int = 10) -> tuple:
        """Run a subprocess command, return (stdout, stderr, returncode)."""
        proc = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: __import__('subprocess').run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        )
        return proc.stdout.strip(), proc.stderr.strip(), proc.returncode

    @staticmethod
    def _windows_quote_ps(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _windows_escape_sendkeys(text: str) -> str:
        special = {
            "+": "{+}",
            "^": "{^}",
            "%": "{%}",
            "~": "{~}",
            "(": "{(}",
            ")": "{)}",
            "{": "{{}",
            "}": "{}}",
        }
        escaped = []
        for char in text.replace("\r\n", "\n"):
            if char == "\n":
                escaped.append("{ENTER}")
            elif char == "\t":
                escaped.append("{TAB}")
            else:
                escaped.append(special.get(char, char))
        return "".join(escaped)

    async def _run_powershell(self, script: str, timeout: int = 20) -> tuple:
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
        return await self._run_cmd(cmd, timeout=timeout)

    async def _windows_type_text_fallback(self, text: str) -> tuple:
        escaped = self._windows_quote_ps(self._windows_escape_sendkeys(text))
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{escaped}')"
        )
        return await self._run_powershell(script, timeout=30)

    def _get_windows_user32(self):
        import ctypes

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        return user32

    def _windows_screen_size(self) -> tuple[int, int]:
        user32 = self._get_windows_user32()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def _windows_mouse_click(self, x: int, y: int, button: str, clicks: int) -> None:
        import time

        user32 = self._get_windows_user32()
        flag_map = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }
        down_flag, up_flag = flag_map.get(button, flag_map["left"])
        user32.SetCursorPos(int(x), int(y))
        for _ in range(max(1, int(clicks))):
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.05)

    def _windows_press_vk(self, vk: int) -> None:
        user32 = self._get_windows_user32()
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0x0002, 0)

    def _windows_key_down(self, vk: int) -> None:
        self._get_windows_user32().keybd_event(vk, 0, 0, 0)

    def _windows_key_up(self, vk: int) -> None:
        self._get_windows_user32().keybd_event(vk, 0, 0x0002, 0)

    def _windows_resolve_vk(self, token: str) -> int:
        normalized = token.strip().lower().replace("_", "").replace(" ", "")
        special_map = {
            "return": 0x0D,
            "enter": 0x0D,
            "tab": 0x09,
            "escape": 0x1B,
            "esc": 0x1B,
            "backspace": 0x08,
            "delete": 0x2E,
            "del": 0x2E,
            "space": 0x20,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
            "home": 0x24,
            "end": 0x23,
            "pageup": 0x21,
            "pgup": 0x21,
            "pagedown": 0x22,
            "pgdn": 0x22,
            "insert": 0x2D,
            "ins": 0x2D,
            "ctrl": 0x11,
            "control": 0x11,
            "shift": 0x10,
            "alt": 0x12,
            "super": 0x5B,
            "win": 0x5B,
            "meta": 0x5B,
        }
        if normalized in special_map:
            return special_map[normalized]
        if normalized.startswith("f") and normalized[1:].isdigit():
            fn = int(normalized[1:])
            if 1 <= fn <= 24:
                return 0x6F + fn
        if len(normalized) == 1 and normalized.isalnum():
            return ord(normalized.upper())
        raise ValueError(f"unsupported Windows key token: {token}")

    def _windows_type_text(self, text: str, delay: int) -> None:
        import ctypes
        import time
        from ctypes import wintypes

        user32 = self._get_windows_user32()
        text = text.replace("\r\n", "\n")
        keyup = 0x0002
        unicode_flag = 0x0004
        input_keyboard = 1
        ulong_ptr = wintypes.WPARAM

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]

        for char in text:
            if char in ("\r", "\n"):
                self._windows_press_vk(0x0D)
            elif char == "\t":
                self._windows_press_vk(0x09)
            else:
                down = INPUT(
                    type=input_keyboard,
                    union=INPUTUNION(
                        ki=KEYBDINPUT(0, ord(char), unicode_flag, 0, 0)
                    ),
                )
                up = INPUT(
                    type=input_keyboard,
                    union=INPUTUNION(
                        ki=KEYBDINPUT(0, ord(char), unicode_flag | keyup, 0, 0)
                    ),
                )
                if user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT)) != 1:
                    raise RuntimeError("SendInput key-down failed")
                if user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT)) != 1:
                    raise RuntimeError("SendInput key-up failed")
            if delay > 0:
                time.sleep(delay / 1000.0)

    @staticmethod
    def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _load_pywinauto_desktop():
        from pywinauto import Desktop

        return Desktop

    @staticmethod
    def _safe_call(method: Any, default: Any = None) -> Any:
        try:
            return method()
        except Exception:
            return default

    @staticmethod
    def _element_info_value(element: Any, key: str, default: Any = None) -> Any:
        info = getattr(element, "element_info", None)
        if info is None:
            return default
        return getattr(info, key, default)

    @staticmethod
    def _rect_to_dict(rect: Any) -> Optional[dict[str, int]]:
        if rect is None:
            return None
        try:
            left = int(getattr(rect, "left"))
            top = int(getattr(rect, "top"))
            right = int(getattr(rect, "right"))
            bottom = int(getattr(rect, "bottom"))
        except Exception:
            return None
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": max(0, right - left),
            "height": max(0, bottom - top),
        }

    def _serialize_windows_element(
        self,
        element: Any,
        *,
        depth: int,
        max_depth: int,
        max_children_per_element: int,
        include_children: bool,
    ) -> dict[str, Any]:
        title = self._safe_call(getattr(element, "window_text", lambda: ""), "")
        friendly_class = self._safe_call(getattr(element, "friendly_class_name", lambda: ""), "")
        rectangle = self._rect_to_dict(self._safe_call(getattr(element, "rectangle", lambda: None)))
        item = {
            "title": str(title or ""),
            "name": str(self._element_info_value(element, "name", "") or ""),
            "class_name": str(self._element_info_value(element, "class_name", "") or ""),
            "friendly_class_name": str(friendly_class or ""),
            "automation_id": str(self._element_info_value(element, "automation_id", "") or ""),
            "control_id": self._element_info_value(element, "control_id"),
            "handle": self._element_info_value(element, "handle"),
            "process_id": self._element_info_value(element, "process_id"),
            "visible": bool(self._safe_call(getattr(element, "is_visible", lambda: False), False)),
            "enabled": bool(self._safe_call(getattr(element, "is_enabled", lambda: False), False)),
            "rectangle": rectangle,
            "children": [],
            "children_truncated": False,
        }
        if not include_children or depth >= max_depth:
            return item

        children = self._safe_call(getattr(element, "children", lambda: []), []) or []
        limited_children = list(children[:max_children_per_element])
        item["children_truncated"] = len(children) > len(limited_children)
        item["children"] = [
            self._serialize_windows_element(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                max_children_per_element=max_children_per_element,
                include_children=include_children,
            )
            for child in limited_children
        ]
        return item

    async def _get_windows_elements(self, args: dict) -> str:
        if self._platform != "win32":
            return "[ERROR] get_windows_elements is Windows only and requires pywinauto."

        backend = str(args.get("backend") or "uia").strip().lower()
        if backend not in {"uia", "win32"}:
            return "[ERROR] Invalid backend. Use 'uia' or 'win32'."
        max_depth = self._bounded_int(args.get("max_depth"), default=3, minimum=0, maximum=8)
        max_windows = self._bounded_int(args.get("max_windows"), default=20, minimum=1, maximum=200)
        max_children = self._bounded_int(args.get("max_children_per_element"), default=80, minimum=0, maximum=500)
        visible_only = bool(args.get("visible_only", True))
        include_children = bool(args.get("include_children", True))

        try:
            Desktop = self._load_pywinauto_desktop()
        except ImportError:
            return (
                "[ERROR] pywinauto is required for get_windows_elements on Windows. "
                "Install it with: pip install pywinauto"
            )

        def collect() -> dict[str, Any]:
            desktop = Desktop(backend=backend)
            windows = list(desktop.windows(visible_only=visible_only))
            limited_windows = windows[:max_windows]
            return {
                "status": "success",
                "platform": self._platform,
                "backend": backend,
                "visible_only": visible_only,
                "include_children": include_children,
                "max_depth": max_depth,
                "max_windows": max_windows,
                "window_count": len(limited_windows),
                "total_windows_seen": len(windows),
                "truncated": len(windows) > len(limited_windows),
                "windows": [
                    self._serialize_windows_element(
                        window,
                        depth=0,
                        max_depth=max_depth,
                        max_children_per_element=max_children,
                        include_children=include_children,
                    )
                    for window in limited_windows
                ],
            }

        try:
            payload = await asyncio.get_event_loop().run_in_executor(None, collect)
        except Exception as exc:
            return f"[ERROR] get_windows_elements failed: {exc}"
        return json.dumps(payload, ensure_ascii=False)

    def _get_vl_client(self):
        """Lazy init vision model client from models.json."""
        if self._vl_client is not None:
            return self._vl_client
        if not self.models_config or not self.models_config.exists():
            return None

        try:
            import json

            config = json.loads(self.models_config.read_text(encoding="utf-8"))
            vision_id = config.get("vision")
            models = config.get("models", [])
            if isinstance(models, dict):
                models = [
                    {**model_cfg, "id": model_id} if isinstance(model_cfg, dict) else {"id": model_id, "model": model_cfg}
                    for model_id, model_cfg in models.items()
                ]
            if not isinstance(models, list):
                return None

            vl_cfg = None
            if vision_id:
                vl_cfg = next((model for model in models if model.get("id") == vision_id), None)
            if not vl_cfg:
                vl_cfg = next(
                    (
                        model
                        for model in models
                        if model.get("supports_vision")
                        or str(model.get("type") or model.get("model_type") or "").lower() == "vision"
                    ),
                    None,
                )
            if not vl_cfg:
                return None

            from openai import OpenAI
            from agentclaw.model.manager import _resolve_env_reference

            self._vl_client = {
                "client": OpenAI(api_key=_resolve_env_reference(vl_cfg.get("api_key")), base_url=vl_cfg.get("base_url")),
                "model": vl_cfg["model"],
            }
            return self._vl_client
        except Exception as exc:
            logger.warning(f"[computer-tools] VL 模型初始化失败: {exc}")
            return None

    async def _read_image(self, file_path: Path, prompt: str) -> str:
        """Analyze a screenshot image via the configured vision model."""
        vl = self._get_vl_client()
        if not vl:
            return (
                f"[Image file: {file_path.name}, {file_path.stat().st_size} bytes]\n"
                "[Warning] 无法分析截图：未配置视觉模型(vision)。"
                "请在 models.json 中添加 \"vision\": \"<model_id>\" 并配置对应的视觉模型。"
            )

        try:
            import base64

            data = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            mime = f"image/{file_path.suffix.lstrip('.').lower()}"
            if mime == "image/jpg":
                mime = "image/jpeg"

            resp = vl["client"].chat.completions.create(
                model=vl["model"],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                    ],
                }],
                max_tokens=2048,
            )
            return f"[Image: {file_path.name}]\n{resp.choices[0].message.content}"
        except Exception as exc:
            return f"[Error] 截图分析失败: {exc}"

    @staticmethod
    def _normalize_screenshot_filename(filename: Optional[str]) -> str:
        import time

        raw_name = str(filename or "").strip() or f"screenshot_{int(time.time())}.png"
        name = Path(raw_name).name.strip() or f"screenshot_{int(time.time())}.png"
        path = Path(name)
        if path.suffix.lower() != ".png":
            name = f"{path.stem or 'screenshot'}.png"
        return name

    @staticmethod
    def _normalize_screenshot_region(region: object) -> Optional[dict[str, int]]:
        if not isinstance(region, dict) or not region:
            return None

        def read_int(key: str, default: int = 0) -> int:
            value = region.get(key, default)
            if value in (None, ""):
                return default
            return int(value)

        x = read_int("x", 0)
        y = read_int("y", 0)
        width = read_int("width", 0)
        height = read_int("height", 0)
        if width <= 0 or height <= 0:
            return None
        return {"x": x, "y": y, "width": width, "height": height}

    async def _screenshot(self, args: dict) -> str:
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        filename = self._normalize_screenshot_filename(args.get("filename"))
        filepath = self._screenshot_dir / filename
        prompt = str(args.get("prompt") or "").strip()
        try:
            region = self._normalize_screenshot_region(args.get("region"))
        except (TypeError, ValueError) as exc:
            return f"[ERROR] Invalid screenshot region: {exc}. Use positive integer width and height, or omit region for full screen."

        if self._platform == "win32":
            if region:
                x, y = region["x"], region["y"]
                width, height = region["width"], region["height"]
            else:
                x, y = 0, 0
                width, height = self._windows_screen_size()
            escaped_path = self._windows_quote_ps(str(filepath))
            script = (
                "Add-Type -AssemblyName System.Drawing; "
                "Add-Type -AssemblyName System.Windows.Forms; "
                f"$bmp = New-Object System.Drawing.Bitmap({width}, {height}); "
                "$graphics = [System.Drawing.Graphics]::FromImage($bmp); "
                f"$graphics.CopyFromScreen({x}, {y}, 0, 0, $bmp.Size); "
                f"$bmp.Save('{escaped_path}', [System.Drawing.Imaging.ImageFormat]::Png); "
                "$graphics.Dispose(); "
                "$bmp.Dispose()"
            )
            stdout, stderr, rc = await self._run_powershell(script, timeout=30)
        elif self._platform == "darwin":
            cmd = ["screencapture", "-x"]
            if region:
                cmd.extend(["-R", f"{region['x']},{region['y']},{region['width']},{region['height']}"])
            cmd.append(str(filepath))
            stdout, stderr, rc = await self._run_cmd(cmd)
        else:
            # Linux: use scrot
            cmd = ["scrot"]
            if region:
                cmd.extend(["-a", f"{region['x']},{region['y']},{region['width']},{region['height']}"])
            cmd.append(str(filepath))
            stdout, stderr, rc = await self._run_cmd(cmd)
        if rc != 0:
            return f"[ERROR] Screenshot failed: {stderr}"

        if filepath.exists():
            result = f"[TOOL_SUCCESS] Screenshot saved: {filepath} (use read_file to view)"
            if prompt:
                result = f"{result}\n\n{await self._read_image(filepath, prompt)}"
            return result
        return f"[ERROR] Screenshot file not created"

    async def _mouse_click(self, args: dict) -> str:
        x, y = args["x"], args["y"]
        button = args.get("button", "left")
        clicks = args.get("clicks", 1)

        if self._platform == "win32":
            self._windows_mouse_click(x, y, button, clicks)
            return f"[TOOL_SUCCESS] Clicked {button} at ({x}, {y})" + (f" x{clicks}" if clicks > 1 else "")
        if self._platform == "darwin":
            # macOS: use cliclick
            btn_map = {"left": "c", "right": "rc", "middle": "mc"}
            action = btn_map.get(button, "c")
            if clicks == 2:
                action = "dc"  # double click
            cmd = ["cliclick", f"{action}:{x},{y}"]
        else:
            # Linux: xdotool
            btn_map = {"left": "1", "right": "3", "middle": "2"}
            btn = btn_map.get(button, "1")
            cmd = ["xdotool", "mousemove", str(x), str(y), "click"]
            if clicks > 1:
                cmd.extend(["--repeat", str(clicks)])
            cmd.append(btn)

        stdout, stderr, rc = await self._run_cmd(cmd)
        if rc != 0:
            return f"[ERROR] Mouse click failed: {stderr}"
        return f"[TOOL_SUCCESS] Clicked {button} at ({x}, {y})" + (f" x{clicks}" if clicks > 1 else "")

    async def _mouse_move(self, args: dict) -> str:
        x, y = args["x"], args["y"]

        if self._platform == "win32":
            self._get_windows_user32().SetCursorPos(int(x), int(y))
            return f"[TOOL_SUCCESS] Mouse moved to ({x}, {y})"
        if self._platform == "darwin":
            cmd = ["cliclick", f"m:{x},{y}"]
        else:
            cmd = ["xdotool", "mousemove", str(x), str(y)]

        stdout, stderr, rc = await self._run_cmd(cmd)
        if rc != 0:
            return f"[ERROR] Mouse move failed: {stderr}"
        return f"[TOOL_SUCCESS] Mouse moved to ({x}, {y})"

    async def _keyboard_type(self, args: dict) -> str:
        text = args["text"]
        delay = args.get("delay", 12)

        if self._platform == "win32":
            try:
                self._windows_type_text(text, int(delay))
            except Exception as exc:
                stdout, stderr, rc = await self._windows_type_text_fallback(text)
                if rc != 0:
                    detail = stderr or stdout or str(exc)
                    return f"[ERROR] Keyboard type failed: {detail}"
            return f"[TOOL_SUCCESS] Typed {len(text)} characters"
        if self._platform == "darwin":
            cmd = ["cliclick", f"t:{text}"]
        else:
            cmd = ["xdotool", "type", "--delay", str(delay), text]

        stdout, stderr, rc = await self._run_cmd(cmd, timeout=30)
        if rc != 0:
            return f"[ERROR] Keyboard type failed: {stderr}"
        return f"[TOOL_SUCCESS] Typed {len(text)} characters"

    async def _keyboard_key(self, args: dict) -> str:
        key = args["key"]

        if self._platform == "win32":
            try:
                vks = [self._windows_resolve_vk(token) for token in key.split("+") if token.strip()]
            except ValueError as exc:
                return f"[ERROR] Key press failed: {exc}"
            if not vks:
                return "[ERROR] Key press failed: empty key combo"
            modifiers = vks[:-1]
            main_key = vks[-1]
            for vk in modifiers:
                self._windows_key_down(vk)
            self._windows_press_vk(main_key)
            for vk in reversed(modifiers):
                self._windows_key_up(vk)
            return f"[TOOL_SUCCESS] Pressed key: {key}"
        if self._platform == "darwin":
            # cliclick uses kp: for key press
            cmd = ["cliclick", f"kp:{key}"]
        else:
            # xdotool key
            cmd = ["xdotool", "key", key]

        stdout, stderr, rc = await self._run_cmd(cmd)
        if rc != 0:
            return f"[ERROR] Key press failed: {stderr}"
        return f"[TOOL_SUCCESS] Pressed key: {key}"

    async def _get_screen_size(self, args: dict) -> str:
        if self._platform == "win32":
            width, height = self._windows_screen_size()
            return f"[TOOL_SUCCESS] Screen size: {width}x{height}"
        if self._platform == "darwin":
            cmd = ["system_profiler", "SPDisplaysDataType"]
            stdout, stderr, rc = await self._run_cmd(cmd)
            if rc == 0:
                import re
                match = re.search(r'Resolution:\s+(\d+)\s*x\s*(\d+)', stdout)
                if match:
                    return f"[TOOL_SUCCESS] Screen size: {match.group(1)}x{match.group(2)}"
            return "[ERROR] Could not determine screen size"
        else:
            cmd = ["xdotool", "getdisplaygeometry"]
            stdout, stderr, rc = await self._run_cmd(cmd)
            if rc != 0:
                return f"[ERROR] Get screen size failed: {stderr}"
            return f"[TOOL_SUCCESS] Screen size: {stdout}"

    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(read_stream, write_stream, self._server.create_initialization_options())
