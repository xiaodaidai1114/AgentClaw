from pathlib import Path
import base64
import pytest

from agentclaw.mcp.builtin_servers.skill_tools import SkillToolsServer
import agentclaw.mcp.builtin_servers.skill_tools as skill_tools_module


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_python_tool_forces_utf8_child_output_encoding(tmp_path: Path, monkeypatch):
    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))
    captured = {}

    async def fake_run_exec_process(cmd, *, cwd, env, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return "bullet: •\n", "", 0

    monkeypatch.setattr(server, "_run_exec_process", fake_run_exec_process)

    output = await server._execute_python({"code": "print('bullet: •')"})

    assert output == "bullet: •\n"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["env"]["PYTHONUTF8"] == "1"


@pytest.mark.asyncio
async def test_shell_tool_encodes_windows_powershell_command_with_unicode(tmp_path: Path, monkeypatch):
    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))
    captured = {}

    async def fake_run_exec_process(cmd, *, cwd, env, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return "***\n", "", 0

    async def fake_run_shell_process(*_args, **_kwargs):
        raise AssertionError("PowerShell -Command should not run through cmd.exe shell")

    monkeypatch.setattr(skill_tools_module.sys, "platform", "win32")
    monkeypatch.setattr(server, "_run_exec_process", fake_run_exec_process)
    monkeypatch.setattr(server, "_run_shell_process", fake_run_shell_process)

    output = await server._execute_shell({
        "command": "powershell -NoProfile -Command \"$body=@{query='*** 个人简历'} | ConvertTo-Json; Write-Output $body\"",
    })

    assert output == "***\n"
    assert captured["cmd"][0] == "powershell"
    assert "-EncodedCommand" in captured["cmd"]
    encoded = captured["cmd"][captured["cmd"].index("-EncodedCommand") + 1]
    decoded_script = base64.b64decode(encoded).decode("utf-16le")
    assert "*** 个人简历" in decoded_script
    assert "[Console]::OutputEncoding" in decoded_script
