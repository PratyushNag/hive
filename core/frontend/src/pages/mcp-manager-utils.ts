import type { McpServerPayload } from "@/api/mcp";

export interface McpFormState {
  name: string;
  description: string;
  transport: "stdio" | "http";
  command: string;
  argsCsv: string;
  cwd: string;
  envJson: string;
  url: string;
  headersJson: string;
  rpcPathsCsv: string;
  oauthCredentialId: string;
}

export function parseStringArrayCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseJsonObject(value: string, fieldName: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(`${fieldName} must be valid JSON object`);
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${fieldName} must be a JSON object`);
  }

  return parsed as Record<string, unknown>;
}

export function buildMcpServerPayload(form: McpFormState): McpServerPayload {
  const base: McpServerPayload = {
    name: form.name.trim(),
    description: form.description.trim(),
    transport: form.transport,
    oauth_credential_id: form.oauthCredentialId.trim() || null,
  };

  if (!base.name) {
    throw new Error("name is required");
  }

  if (form.transport === "stdio") {
    base.command = form.command.trim();
    base.args = parseStringArrayCsv(form.argsCsv);
    base.cwd = form.cwd.trim() || null;
    base.env = parseJsonObject(form.envJson, "env");
    if (!base.command) {
      throw new Error("command is required for stdio transport");
    }
  } else {
    base.url = form.url.trim();
    base.headers = parseJsonObject(form.headersJson, "headers");
    base.rpc_paths = parseStringArrayCsv(form.rpcPathsCsv);
    if (!base.url) {
      throw new Error("url is required for http transport");
    }
  }

  return base;
}
