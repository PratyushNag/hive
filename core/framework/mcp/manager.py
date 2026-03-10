"""Centralized MCP manager service (registry + runtime operations)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.mcp.client import MCPClient
from framework.mcp.errors import MCPAuthRequiredError, MCPAuthRequiredExternalError
from framework.mcp.models import MCPServerConfig


class MCPManagerError(RuntimeError):
    """Base exception for centralized MCP manager."""


class MCPManagerValidationError(MCPManagerError):
    """Raised when MCP manager payloads are invalid."""


class MCPManagerNotFoundError(MCPManagerError):
    """Raised when an MCP server record is not found."""


class MCPSecretResolutionError(MCPManagerValidationError):
    """Raised when a credential reference cannot be resolved."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_sensitive_key(key_name: str) -> bool:
    lowered = key_name.strip().lower()
    markers = (
        "token",
        "secret",
        "password",
        "authorization",
        "api_key",
        "apikey",
        "access_key",
    )
    return any(marker in lowered for marker in markers)


def _validate_secret_ref(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MCPManagerValidationError(
            f"{field_name} values must be credential ref objects: "
            '{"credential_id":"...","key_name":"..."}'
        )

    credential_id = value.get("credential_id")
    key_name = value.get("key_name", "api_key")
    if not isinstance(credential_id, str) or not credential_id.strip():
        raise MCPManagerValidationError(f"{field_name}.credential_id is required")
    if not isinstance(key_name, str) or not key_name.strip():
        raise MCPManagerValidationError(f"{field_name}.key_name must be a non-empty string")

    normalized = {
        "credential_id": credential_id.strip(),
        "key_name": key_name.strip(),
    }
    prefix = value.get("prefix")
    if prefix is not None:
        if not isinstance(prefix, str):
            raise MCPManagerValidationError(f"{field_name}.prefix must be a string")
        normalized["prefix"] = prefix

    unexpected = set(value.keys()) - {"credential_id", "key_name", "prefix"}
    if unexpected:
        raise MCPManagerValidationError(
            f"Unexpected keys in {field_name}: {sorted(unexpected)}"
        )

    return normalized


def _validate_secret_map(
    mapping: Any,
    field_name: str,
) -> dict[str, Any]:
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise MCPManagerValidationError(f"{field_name} must be an object")

    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise MCPManagerValidationError(f"{field_name} keys must be non-empty strings")

        if isinstance(value, str):
            if _is_sensitive_key(key):
                raise MCPManagerValidationError(
                    f"{field_name}.{key} looks sensitive. Use credential ref object instead of plain string."
                )
            # Preserve explicit literals for non-sensitive keys.
            normalized[key] = value
            continue

        if isinstance(value, dict) and set(value.keys()) == {"literal"}:
            literal = value.get("literal")
            if not isinstance(literal, str):
                raise MCPManagerValidationError(
                    f"{field_name}.{key}.literal must be a string"
                )
            if _is_sensitive_key(key):
                raise MCPManagerValidationError(
                    f"{field_name}.{key} looks sensitive. Use credential ref object instead of plain string."
                )
            normalized[key] = literal
            continue

        normalized[key] = _validate_secret_ref(value, f"{field_name}.{key}")

    return normalized


class MCPManagerStore:
    """File-backed storage for centralized MCP server records."""

    def __init__(self, path: Path | None = None):
        self._path = path or (Path.home() / ".hive" / "mcp" / "servers.json")
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._read_locked()
            return list(payload["servers"])

    def get_server(self, server_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._read_locked()
            for item in payload["servers"]:
                if item["id"] == server_id:
                    return dict(item)
        return None

    def get_server_by_name(self, server_name: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._read_locked()
            for item in payload["servers"]:
                if item["name"] == server_name:
                    return dict(item)
        return None

    def create_server(self, server: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self._read_locked()
            if any(item["name"] == server["name"] for item in payload["servers"]):
                raise MCPManagerValidationError(f"MCP server name already exists: {server['name']}")

            now = _utc_now_iso()
            record = {
                **server,
                "id": str(uuid.uuid4()),
                "created_at": now,
                "updated_at": now,
            }
            payload["servers"].append(record)
            self._write_locked(payload)
            return dict(record)

    def update_server(self, server_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self._read_locked()
            idx = -1
            current: dict[str, Any] | None = None
            for i, item in enumerate(payload["servers"]):
                if item["id"] == server_id:
                    idx = i
                    current = item
                    break
            if idx < 0 or current is None:
                raise MCPManagerNotFoundError(f"MCP server not found: {server_id}")

            new_name = patch.get("name")
            if isinstance(new_name, str) and new_name != current["name"]:
                if any(item["name"] == new_name for item in payload["servers"]):
                    raise MCPManagerValidationError(f"MCP server name already exists: {new_name}")

            updated = {
                **current,
                **patch,
                "id": current["id"],
                "created_at": current["created_at"],
                "updated_at": _utc_now_iso(),
            }
            payload["servers"][idx] = updated
            self._write_locked(payload)
            return dict(updated)

    def delete_server(self, server_id: str) -> bool:
        with self._lock:
            payload = self._read_locked()
            before = len(payload["servers"])
            payload["servers"] = [item for item in payload["servers"] if item["id"] != server_id]
            if len(payload["servers"]) == before:
                return False
            self._write_locked(payload)
            return True

    def _read_locked(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"servers": []}

        try:
            with open(self._path, encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise MCPManagerError(f"Invalid MCP registry JSON at {self._path}: {exc}") from exc
        except OSError as exc:
            raise MCPManagerError(f"Failed to read MCP registry at {self._path}: {exc}") from exc

        servers = payload.get("servers")
        if not isinstance(servers, list):
            raise MCPManagerError("MCP registry is malformed: expected 'servers' list")
        return {"servers": servers}

    def _write_locked(self, payload: dict[str, Any]) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)

        tmp = parent / f"{self._path.name}.tmp"
        data = json.dumps(payload, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)


class MCPManagerService:
    """CRUD + runtime operations for centralized MCP server manager."""

    def __init__(self, store: MCPManagerStore | None = None, credential_store: Any | None = None):
        self._store = store or MCPManagerStore()
        self._credential_store = credential_store

    def list_servers(self) -> list[dict[str, Any]]:
        return self._store.list_servers()

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload, partial=False)
        return self._store.create_server(normalized)

    def update_server(self, server_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self._store.get_server(server_id)
        if existing is None:
            raise MCPManagerNotFoundError(f"MCP server not found: {server_id}")

        merged = {**existing, **patch}
        transport_changed = (
            "transport" in patch
            and patch.get("transport") in ("stdio", "http")
            and patch.get("transport") != existing.get("transport")
        )
        if transport_changed:
            if patch["transport"] == "stdio":
                merged.update({"url": None, "headers": {}, "rpc_paths": []})
            else:
                merged.update({"command": None, "args": [], "cwd": None, "env": {}})

        normalized = self._normalize_payload(merged, partial=False)
        # Keep patch small so unknown keys don't leak through.
        allowed_keys = {
            "name",
            "description",
            "transport",
            "command",
            "args",
            "cwd",
            "env",
            "url",
            "headers",
            "rpc_paths",
            "oauth_credential_id",
        }
        if transport_changed:
            normalized_patch = {k: normalized[k] for k in allowed_keys}
        else:
            normalized_patch = {k: normalized[k] for k in allowed_keys if k in patch}
        return self._store.update_server(server_id, normalized_patch)

    def delete_server(self, server_id: str) -> bool:
        return self._store.delete_server(server_id)

    def get_server(self, server_id: str) -> dict[str, Any]:
        found = self._store.get_server(server_id)
        if found is None:
            raise MCPManagerNotFoundError(f"MCP server not found: {server_id}")
        return found

    def resolve_server(
        self,
        *,
        server_id: str | None = None,
        server_name: str | None = None,
    ) -> dict[str, Any]:
        if bool(server_id) == bool(server_name):
            raise MCPManagerValidationError("Exactly one of server_id or server_name is required")

        if server_id:
            found = self._store.get_server(server_id)
            if found is None:
                raise MCPManagerNotFoundError(f"MCP server not found: {server_id}")
            return found

        assert server_name is not None
        found = self._store.get_server_by_name(server_name)
        if found is None:
            raise MCPManagerNotFoundError(f"MCP server not found: {server_name}")
        return found

    def test_server(self, server_id: str) -> dict[str, Any]:
        record = self.get_server(server_id)
        try:
            config = self._build_runtime_config(record)
            tools = self._with_client(config, lambda client: client.list_tools())
            return self._envelope(
                ok=True,
                status="connected",
                message=f"Connected to MCP server '{record['name']}'",
                record=record,
                raw={"tool_count": len(tools)},
            )
        except MCPAuthRequiredError as exc:
            return self._envelope(
                ok=False,
                status="auth_required",
                message=str(exc),
                record=record,
                raw=exc.payload,
            )
        except MCPAuthRequiredExternalError as exc:
            return self._envelope(
                ok=False,
                status="integration_not_supported",
                message=str(exc),
                record=record,
                raw=exc.payload,
            )
        except Exception as exc:
            return self._envelope(
                ok=False,
                status="failed",
                message=f"Failed to connect to MCP server '{record['name']}'",
                record=record,
                raw={"error": str(exc), "type": type(exc).__name__},
            )

    def list_server_tools(self, server_id: str) -> dict[str, Any]:
        record = self.get_server(server_id)
        try:
            config = self._build_runtime_config(record)
            tools = self._with_client(config, lambda client: client.list_tools())
            envelope = self._envelope(
                ok=True,
                status="connected",
                message=f"Discovered {len(tools)} tools",
                record=record,
                raw={"tool_count": len(tools)},
            )
            envelope["tools"] = self._to_jsonable(tools)
            return envelope
        except MCPAuthRequiredError as exc:
            return self._envelope(
                ok=False,
                status="auth_required",
                message=str(exc),
                record=record,
                raw=exc.payload,
            )
        except MCPAuthRequiredExternalError as exc:
            return self._envelope(
                ok=False,
                status="integration_not_supported",
                message=str(exc),
                record=record,
                raw=exc.payload,
            )
        except Exception as exc:
            return self._envelope(
                ok=False,
                status="failed",
                message=f"Failed to list tools for '{record['name']}'",
                record=record,
                raw={"error": str(exc), "type": type(exc).__name__},
            )

    def invoke_tool(
        self,
        *,
        server_id: str | None = None,
        server_name: str | None = None,
        tool_name: str,
        tool_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise MCPManagerValidationError("tool_name is required")
        if not isinstance(tool_arguments, dict):
            raise MCPManagerValidationError("tool_arguments must be an object")

        record = self.resolve_server(server_id=server_id, server_name=server_name)

        try:
            config = self._build_runtime_config(record)
            result = self._with_client(
                config,
                lambda client: client.call_tool(tool_name, tool_arguments),
            )
            envelope = self._envelope(
                ok=True,
                status="ok",
                message=f"Tool '{tool_name}' executed",
                record=record,
                raw={"tool_name": tool_name},
            )
            envelope["result"] = self._to_jsonable(result)
            return envelope
        except MCPAuthRequiredError as exc:
            return self._envelope(
                ok=False,
                status="auth_required",
                message=str(exc),
                record=record,
                raw=exc.payload,
            )
        except MCPAuthRequiredExternalError as exc:
            return self._envelope(
                ok=False,
                status="integration_not_supported",
                message=str(exc),
                record=record,
                raw=exc.payload,
            )
        except Exception as exc:
            return self._envelope(
                ok=False,
                status="error",
                message=f"Tool '{tool_name}' execution failed",
                record=record,
                raw={"error": str(exc), "type": type(exc).__name__},
            )

    def _normalize_payload(self, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        _ = partial
        if not isinstance(payload, dict):
            raise MCPManagerValidationError("Payload must be an object")

        name = payload.get("name")
        transport = payload.get("transport")

        if not isinstance(name, str) or not name.strip():
            raise MCPManagerValidationError("name is required")
        if transport not in ("stdio", "http"):
            raise MCPManagerValidationError("transport must be 'stdio' or 'http'")

        description = payload.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise MCPManagerValidationError("description must be a string")

        normalized: dict[str, Any] = {
            "name": name.strip(),
            "description": description,
            "transport": transport,
            "oauth_credential_id": payload.get("oauth_credential_id"),
        }

        oauth_credential_id = normalized["oauth_credential_id"]
        if oauth_credential_id is not None and (
            not isinstance(oauth_credential_id, str) or not oauth_credential_id.strip()
        ):
            raise MCPManagerValidationError("oauth_credential_id must be a non-empty string")

        if transport == "stdio":
            command = payload.get("command")
            if not isinstance(command, str) or not command.strip():
                raise MCPManagerValidationError("command is required for stdio transport")

            args = payload.get("args", [])
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise MCPManagerValidationError("args must be a string array")

            cwd = payload.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                raise MCPManagerValidationError("cwd must be a string")

            env = _validate_secret_map(payload.get("env", {}), "env")

            if payload.get("url") not in (None, ""):
                raise MCPManagerValidationError("url is not valid for stdio transport")
            if payload.get("headers") not in (None, {}):
                raise MCPManagerValidationError("headers are not valid for stdio transport")
            if payload.get("rpc_paths") not in (None, []):
                raise MCPManagerValidationError("rpc_paths are not valid for stdio transport")

            normalized.update(
                {
                    "command": command.strip(),
                    "args": args,
                    "cwd": cwd,
                    "env": env,
                    "url": None,
                    "headers": {},
                    "rpc_paths": [],
                }
            )
        else:
            url = payload.get("url")
            if not isinstance(url, str) or not url.strip():
                raise MCPManagerValidationError("url is required for http transport")

            headers = _validate_secret_map(payload.get("headers", {}), "headers")

            rpc_paths = payload.get("rpc_paths", [])
            if not isinstance(rpc_paths, list) or not all(isinstance(path, str) for path in rpc_paths):
                raise MCPManagerValidationError("rpc_paths must be a string array")

            if payload.get("command") not in (None, ""):
                raise MCPManagerValidationError("command is not valid for http transport")
            if payload.get("args") not in (None, []):
                raise MCPManagerValidationError("args are not valid for http transport")
            if payload.get("cwd") not in (None, ""):
                raise MCPManagerValidationError("cwd is not valid for http transport")
            if payload.get("env") not in (None, {}):
                raise MCPManagerValidationError("env is not valid for http transport")

            normalized.update(
                {
                    "url": url.strip(),
                    "headers": headers,
                    "rpc_paths": rpc_paths,
                    "command": None,
                    "args": [],
                    "cwd": None,
                    "env": {},
                }
            )

        return normalized

    def _resolve_credential_ref(self, ref: dict[str, str]) -> str:
        literal = ref.get("literal")
        if literal is not None:
            return literal

        credential_id = ref["credential_id"]
        key_name = ref.get("key_name", "api_key")
        store = self._credential_store
        if store is None:
            raise MCPSecretResolutionError(
                f"Credential store unavailable while resolving '{credential_id}'"
            )

        credential = store.get_credential(credential_id, refresh_if_needed=False)
        if credential is None:
            raise MCPSecretResolutionError(
                f"Credential '{credential_id}' not found while resolving MCP manager secret refs"
            )

        value = credential.get_key(key_name)
        if not value:
            raise MCPSecretResolutionError(
                f"Credential '{credential_id}' is missing key '{key_name}'"
            )

        prefix = ref.get("prefix")
        if prefix:
            return f"{prefix}{value}"
        return value

    def _resolve_secret_map(self, mapping: dict[str, Any]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for key, value in mapping.items():
            if isinstance(value, str):
                resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_credential_ref(value)
            else:
                raise MCPSecretResolutionError(
                    f"Invalid secret ref value for '{key}'. Expected string or object."
                )
        return resolved

    def _build_runtime_config(self, record: dict[str, Any]) -> MCPServerConfig:
        transport = record["transport"]
        if transport == "stdio":
            return MCPServerConfig(
                name=record["name"],
                transport="stdio",
                command=record["command"],
                args=list(record.get("args") or []),
                env=self._resolve_secret_map(record.get("env") or {}),
                cwd=record.get("cwd"),
                oauth_credential_id=record.get("oauth_credential_id"),
                description=record.get("description") or "",
            )

        return MCPServerConfig(
            name=record["name"],
            transport="http",
            url=record.get("url"),
            headers=self._resolve_secret_map(record.get("headers") or {}),
            rpc_paths=list(record.get("rpc_paths") or []),
            oauth_credential_id=record.get("oauth_credential_id"),
            description=record.get("description") or "",
        )

    def _with_client(self, config: MCPServerConfig, callback):
        client = MCPClient(config)
        try:
            client.connect()
            return callback(client)
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): MCPManagerService._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [MCPManagerService._to_jsonable(v) for v in value]
        if is_dataclass(value):
            return MCPManagerService._to_jsonable(asdict(value))
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return MCPManagerService._to_jsonable(model_dump())
        to_dict = getattr(value, "dict", None)
        if callable(to_dict):
            return MCPManagerService._to_jsonable(to_dict())
        return str(value)

    @staticmethod
    def _envelope(
        *,
        ok: bool,
        status: str,
        message: str,
        record: dict[str, Any],
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": ok,
            "status": status,
            "message": message,
            "server_id": record["id"],
            "server_name": record["name"],
            "raw": MCPManagerService._to_jsonable(raw),
        }
