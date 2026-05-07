"""
AgentClaw 统一日志管理器

使用方式:
    from agentclaw.logger.config import get_logger
    
    logger = get_logger(__name__)
    logger.info("消息")
    logger.debug("调试信息")
"""
import logging
import os
import sys
from typing import Optional
from pathlib import Path
from datetime import date


# 日志格式
_FORMAT_SIMPLE = "%(levelname)s | %(name)s | %(message)s"
_FORMAT_DETAILED = "%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s"
_DEFAULT_LOG_FILE = "logs/agentclaw.log"
_DEFAULT_CONSOLE_LEVEL = "WARNING"

# 全局配置状态
_initialized = False
_log_level = logging.INFO
_log_file: Optional[str] = None


def _build_daily_log_path(log_file: str, day: date) -> str:
    """Convert a base log path into a dated daily log path."""
    path = Path(log_file)
    suffix = "".join(path.suffixes)
    stem = path.name[:-len(suffix)] if suffix else path.name
    dated_name = f"{stem}-{day.isoformat()}{suffix}"
    return str(path.with_name(dated_name))


class DailyFileHandler(logging.FileHandler):
    """File handler that writes to a date-stamped file and switches at day boundaries."""

    def __init__(
        self,
        filename: str,
        mode: str = "a",
        encoding: Optional[str] = None,
        delay: bool = False,
        errors: Optional[str] = None,
        date_provider=None,
    ) -> None:
        self._base_log_file = str(Path(filename))
        self._date_provider = date_provider or date.today
        self._current_date = self._date_provider()
        dated_path = _build_daily_log_path(self._base_log_file, self._current_date)
        Path(dated_path).parent.mkdir(parents=True, exist_ok=True)
        super().__init__(dated_path, mode=mode, encoding=encoding, delay=delay, errors=errors)

    def _switch_to_current_day_file(self) -> None:
        next_date = self._date_provider()
        if next_date == self._current_date:
            return

        self.acquire()
        try:
            next_date = self._date_provider()
            if next_date == self._current_date:
                return

            self._current_date = next_date
            dated_path = _build_daily_log_path(self._base_log_file, self._current_date)
            Path(dated_path).parent.mkdir(parents=True, exist_ok=True)

            if self.stream:
                self.stream.flush()
                self.stream.close()
                self.stream = None

            self.baseFilename = os.path.abspath(dated_path)
            if not self.delay:
                self.stream = self._open()
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        self._switch_to_current_day_file()
        super().emit(record)


class LoggerManager:
    """统一日志管理器"""
    
    _instance: Optional["LoggerManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup_done = False
        return cls._instance
    
    def setup(
        self,
        level: str = "INFO",
        log_file: Optional[str] = None,
        format_style: str = "simple",
        propagate: bool = False,
    ) -> None:
        """
        初始化日志系统
        
        Args:
            level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
            log_file: 日志文件路径（可选）
            format_style: 格式风格 (simple/detailed)
            propagate: 是否传播到根 logger
        """
        global _log_level, _log_file
        _log_level = getattr(logging, level.upper(), logging.INFO)
        _log_file = self._resolve_log_file(log_file)
        
        # 选择格式
        fmt = _FORMAT_DETAILED if format_style == "detailed" else _FORMAT_SIMPLE
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

        app_handlers = self._build_handlers(formatter, _log_file)
        root_handlers = self._build_handlers(formatter, _log_file)

        # 配置 agentclaw logger：业务日志不传播，避免重复
        app_logger = logging.getLogger("agentclaw")
        self._reset_handlers(app_logger)
        app_logger.setLevel(_log_level)
        for handler in app_handlers:
            app_logger.addHandler(handler)
        app_logger.propagate = propagate

        # 配置 root logger：接管 uvicorn / 第三方库日志，统一写文件
        root_logger = logging.getLogger()
        self._reset_handlers(root_logger)
        root_logger.setLevel(_log_level)
        for handler in root_handlers:
            root_logger.addHandler(handler)

        # 抑制 MCP SDK 的 JSONRPC 解析错误（npm stdout 污染导致的无害错误）
        self._suppress_mcp_jsonrpc_noise()

        self._setup_done = True
    
    def set_level(self, level: str) -> None:
        """动态调整日志级别"""
        global _log_level
        _log_level = getattr(logging, level.upper(), logging.INFO)
        console_level = self._resolve_console_level()

        root_logger = logging.getLogger("agentclaw")
        root_logger.setLevel(_log_level)
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(max(_log_level, console_level))
        base_logger = logging.getLogger()
        base_logger.setLevel(_log_level)
        for handler in base_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(max(_log_level, console_level))

    @staticmethod
    def _resolve_log_file(log_file: Optional[str]) -> str:
        env_log_file = os.getenv("AGENTCLAW_LOG_FILE") or os.getenv("LOG_FILE")
        data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
        data_dir_log_file = str(Path(data_dir).expanduser() / "logs" / "agentclaw.log") if data_dir else ""
        raw_path = Path(log_file or env_log_file or data_dir_log_file or _DEFAULT_LOG_FILE).expanduser()
        if raw_path.is_absolute():
            return str(raw_path)
        return str((LoggerManager._resolve_project_dir() / raw_path).resolve())

    @staticmethod
    def _resolve_project_dir() -> Path:
        env_project_dir = os.getenv("AGENTCLAW_PROJECT_DIR")
        if env_project_dir:
            return Path(env_project_dir).expanduser().resolve()

        main_module = sys.modules.get("__main__")
        main_file = getattr(main_module, "__file__", None)
        if main_file:
            main_path = Path(main_file).expanduser().resolve()
            if main_path.name == "server.py":
                return main_path.parent

        cwd = Path.cwd().resolve()
        if (cwd / "server.py").exists() or (cwd / "agents").exists():
            return cwd

        return cwd

    @staticmethod
    def _reset_handlers(logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    @staticmethod
    def _build_handlers(formatter: logging.Formatter, log_file: str) -> list[logging.Handler]:
        console_level = LoggerManager._resolve_console_level()

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(console_level)

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = DailyFileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_FORMAT_DETAILED))
        file_handler.setLevel(logging.DEBUG)
        return [console_handler, file_handler]

    @staticmethod
    def _resolve_console_level() -> int:
        console_level_name = os.getenv("LOG_CONSOLE_LEVEL", _DEFAULT_CONSOLE_LEVEL)
        return getattr(logging, console_level_name.upper(), logging.CRITICAL)

    @staticmethod
    def _suppress_mcp_jsonrpc_noise() -> None:
        """抑制 MCP SDK stdio 传输层的 JSONRPC 解析错误日志

        MCP Server 通过 stdio 通信时，子进程 stdout 可能混入非 JSON 输出
        （如 npm install 信息）。MCP SDK 的 stdout_reader 会用
        logger.exception() 打印完整 traceback，对用户造成干扰。
        这里通过 logging filter 静默这类特定日志。
        """

        class _JSONRPCNoiseFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                return "Failed to parse JSONRPC message" not in record.getMessage()

        mcp_stdio_logger = logging.getLogger("mcp.client.stdio")
        mcp_stdio_logger.addFilter(_JSONRPCNoiseFilter())
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        获取 logger 实例
        
        Args:
            name: 模块名（通常使用 __name__）
        
        Returns:
            配置好的 logger
        """
        # 确保初始化
        if not self._setup_done:
            self.setup()
        
        # 统一前缀
        if not name.startswith("agentclaw"):
            name = f"agentclaw.{name}"
        
        return logging.getLogger(name)


# 单例实例
_manager = LoggerManager()


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_style: str = "simple",
) -> None:
    """
    初始化日志系统（应用入口调用一次）
    
    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径（可选）
        format_style: 格式风格 (simple/detailed)
    
    Example:
        setup_logging(level="DEBUG", log_file="logs/app.log")
    """
    _manager.setup(level=level, log_file=log_file, format_style=format_style)


def get_current_log_file() -> Optional[str]:
    """Return the actual log file path used today, including the daily date suffix."""
    if not _log_file:
        return None
    return _build_daily_log_path(_log_file, date.today())


def get_logger(name: str) -> logging.Logger:
    """
    获取 logger（各模块使用）
    
    Args:
        name: 模块名（通常使用 __name__）
    
    Example:
        logger = get_logger(__name__)
        logger.info("工作流开始执行")
    """
    return _manager.get_logger(name)


def set_log_level(level: str) -> None:
    """
    动态调整日志级别
    
    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
    """
    _manager.set_level(level)
