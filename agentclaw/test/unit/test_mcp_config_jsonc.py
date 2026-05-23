from pathlib import Path

import pytest

from agentclaw.mcp.config import MCPConfig, TransportType


pytestmark = pytest.mark.unit


def test_mcp_config_from_file_accepts_jsonc_comments(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            // Disabled server kept as an example.
            // "disabled-server": {
            //   "command": "uvx",
            //   "args": ["disabled-mcp-server"]
            // },
            "WebSearch": {
              "type": "remote",
              "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp",
              "headers": {
                "Authorization": "Bearer token"
              }
            },
            /*
             * Block comments are also allowed in hand-edited config.
             */
            "fetch": {
              "command": "uvx",
              "args": ["mcp-server-fetch"]
            }
          }
        }
        """,
        encoding="utf-8",
    )

    config = MCPConfig.from_file(config_path)

    assert set(config.servers) == {"WebSearch", "fetch"}
    assert config.get_server("WebSearch").url == "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp"
    assert config.get_server("WebSearch").headers == {"Authorization": "Bearer token"}
    assert config.get_server("fetch").command == "uvx"


def test_mcp_config_jsonc_parser_preserves_comment_markers_inside_strings(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        r'''
        {
          "mcpServers": {
            "stringy": {
              "command": "echo",
              "args": [
                "https://example.com/path//still-string",
                "literal /* not a comment */ value",
                "escaped quote \" // still string"
              ]
            }
          }
        }
        ''',
        encoding="utf-8",
    )

    config = MCPConfig.from_file(config_path)

    assert config.get_server("stringy").args == [
        "https://example.com/path//still-string",
        "literal /* not a comment */ value",
        'escaped quote " // still string',
    ]


def test_mcp_config_type_remote_defaults_to_streamable_http(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "WebSearch": {
              "type": "remote",
              "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp",
              "headers": {
                "Authorization": "Bearer token"
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )

    config = MCPConfig.from_file(config_path)
    server = config.get_server("WebSearch")

    assert server.transport == TransportType.STREAMABLE_HTTP
    assert server.transport_auto is False


def test_mcp_config_url_without_transport_uses_auto_detection(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "jina-mcp-server": {
              "url": "https://mcp.jina.ai/v1",
              "headers": {
                "Authorization": "Bearer token"
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )

    config = MCPConfig.from_file(config_path)
    server = config.get_server("jina-mcp-server")

    assert server.transport == TransportType.SSE
    assert server.transport_auto is True


def test_mcp_config_records_detected_transport_without_dropping_comments(tmp_path: Path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            // Keep this commented example.
            // "disabled": {"url": "https://example.invalid/mcp"},
            "jina-mcp-server": {
              "url": "https://mcp.jina.ai/v1",
              "headers": {
                "Authorization": "Bearer token"
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )

    config = MCPConfig.from_file(config_path)
    config.record_detected_transport("jina-mcp-server", TransportType.STREAMABLE_HTTP)

    updated = config_path.read_text(encoding="utf-8")
    server = MCPConfig.from_file(config_path).get_server("jina-mcp-server")

    assert '// Keep this commented example.' in updated
    assert '"transport": "streamable_http"' in updated
    assert server.transport == TransportType.STREAMABLE_HTTP
    assert server.transport_auto is False
