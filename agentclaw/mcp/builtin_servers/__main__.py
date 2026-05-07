"""Module execution entry for built-in MCP servers."""

import sys
import os

# 修复: 当 CWD 包含 mcp/ 目录时（例如从 agentclaw/ 目录启动服务器），
# python -m 会将 CWD 加入 sys.path[0]，导致 `from mcp.server import Server`
# 解析到本地的 agentclaw/mcp/ 而非第三方 mcp 包。
# 这里临时移除有冲突的路径，预先加载正确的第三方 mcp 包。
_problematic = []
for _p in list(sys.path):
    _resolved = os.path.abspath(_p) if _p else os.getcwd()
    _local_mcp = os.path.join(_resolved, 'mcp', '__init__.py')
    if os.path.isfile(_local_mcp) and 'site-packages' not in _resolved:
        _problematic.append(_p)
        sys.path.remove(_p)

# 预加载第三方 mcp 包
import mcp.server  # noqa: E402

# 恢复 sys.path
for _p in reversed(_problematic):
    sys.path.insert(0, _p)

from .registry import main  # noqa: E402

if __name__ == "__main__":
    main()
