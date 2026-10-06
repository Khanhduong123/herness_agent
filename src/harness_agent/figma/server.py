"""Figma Stdio MCP Server handling JSON-RPC 2.0 protocol."""

import json
import sys
from typing import Any, Dict, Optional

from harness_agent.figma.client import FigmaClient
from harness_agent.figma.extractor import FigmaExtractor


class FigmaMCPServer:
    """Stdio-based JSON-RPC 2.0 MCP server exposing Figma inspection & export tools."""

    def __init__(self, client: Optional[FigmaClient] = None) -> None:
        self.client = client

    def _get_client(self) -> FigmaClient:
        if self.client is None:
            self.client = FigmaClient()
        return self.client

    def _resolve_file_and_node(
        self, url_or_key: str, node_id: Optional[str] = None
    ) -> tuple[str, Optional[str]]:
        client = self._get_client()
        if "figma.com" in url_or_key:
            parsed_key, parsed_node = client.parse_figma_url(url_or_key)
            return parsed_key, node_id or parsed_node
        return url_or_key, node_id

    def list_tools(self) -> list[Dict[str, Any]]:
        """Returns standard MCP tool list schema."""
        return [
            {
                "name": "get_frame_layout",
                "description": "Extracts Auto-layout structure and sizing for a Figma node.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url_or_key": {
                            "type": "string",
                            "description": "Figma file key or complete file/design URL",
                        },
                        "node_id": {
                            "type": "string",
                            "description": "Target frame node ID (e.g., '1:2' or '10-25')",
                        },
                    },
                    "required": ["url_or_key"],
                },
            },
            {
                "name": "get_design_tokens",
                "description": "Extracts design tokens (colors, typography, radius, shadows).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url_or_key": {
                            "type": "string",
                            "description": "Figma file key or complete file/design URL",
                        },
                        "node_id": {
                            "type": "string",
                            "description": "Target node ID to extract tokens from",
                        },
                    },
                    "required": ["url_or_key"],
                },
            },
            {
                "name": "export_node_image",
                "description": "Renders node image, saves binary to local disk, returns path.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url_or_key": {
                            "type": "string",
                            "description": "Figma file key or complete file/design URL",
                        },
                        "node_id": {
                            "type": "string",
                            "description": "Target node ID to export",
                        },
                        "output_dir": {
                            "type": "string",
                            "description": "Directory where image will be saved",
                            "default": "assets/images",
                        },
                        "format": {
                            "type": "string",
                            "description": "Image format (png, jpg, svg, pdf)",
                            "default": "png",
                        },
                    },
                    "required": ["url_or_key", "node_id"],
                },
            },
        ]

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches an MCP tool call."""
        client = self._get_client()

        if tool_name == "get_frame_layout":
            url_or_key = arguments["url_or_key"]
            node_id = arguments.get("node_id")
            file_key, resolved_node_id = self._resolve_file_and_node(url_or_key, node_id)

            if resolved_node_id:
                res = client.get_file_nodes(file_key, [resolved_node_id])
                nodes = res.get("nodes", {})
                node_data = nodes.get(resolved_node_id, {}).get("document", {})
            else:
                res = client.get_file(file_key, depth=2)
                node_data = res.get("document", {})

            layout = FigmaExtractor.extract_frame_layout(node_data)
            return {"content": [{"type": "text", "text": layout.model_dump_json(indent=2)}]}

        elif tool_name == "get_design_tokens":
            url_or_key = arguments["url_or_key"]
            node_id = arguments.get("node_id")
            file_key, resolved_node_id = self._resolve_file_and_node(url_or_key, node_id)

            if resolved_node_id:
                res = client.get_file_nodes(file_key, [resolved_node_id])
                nodes = res.get("nodes", {})
                node_data = nodes.get(resolved_node_id, {}).get("document", {})
            else:
                res = client.get_file(file_key, depth=2)
                node_data = res.get("document", {})

            tokens = FigmaExtractor.extract_design_tokens(node_data)
            return {"content": [{"type": "text", "text": tokens.model_dump_json(indent=2)}]}

        elif tool_name == "export_node_image":
            url_or_key = arguments["url_or_key"]
            node_id = arguments["node_id"]
            file_key, resolved_node_id = self._resolve_file_and_node(url_or_key, node_id)
            target_node = resolved_node_id or node_id
            output_dir = arguments.get("output_dir", "assets/images")
            fmt = arguments.get("format", "png")

            export = client.export_node_image(
                file_key=file_key,
                node_id=target_node,
                output_dir=output_dir,
                format=fmt,
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "node_id": export.node_id,
                                "local_path": export.local_path,
                                "format": export.format,
                                "file_size_bytes": export.file_size_bytes,
                            },
                            indent=2,
                        ),
                    }
                ]
            }
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handles a single JSON-RPC 2.0 message."""
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        if not method:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32600, "message": "Invalid Request: missing method"},
            }

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "figma-local-mcp", "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result = self.call_tool(tool_name, arguments)
            elif method == "notifications/initialized":
                return None
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32000, "message": str(e)},
            }

    def run_stdio(self) -> None:
        """Runs the stdio JSON-RPC loop until EOF."""
        for line in sys.stdin:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                msg = json.loads(line_str)
                response = self.handle_message(msg)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError as err:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {err}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


def main() -> None:
    server = FigmaMCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
