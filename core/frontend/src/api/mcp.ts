import { api } from "./client";
import type {
  McpInvokeRequest,
  McpOperationEnvelope,
  McpServerRecord,
  McpToolsResponse,
} from "./types";

export type McpServerPayload = {
  name: string;
  description?: string;
  transport: "stdio" | "http";
  command?: string | null;
  args?: string[];
  cwd?: string | null;
  env?: Record<string, unknown>;
  url?: string | null;
  headers?: Record<string, unknown>;
  rpc_paths?: string[];
  oauth_credential_id?: string | null;
};

export const mcpApi = {
  listServers: () => api.get<{ servers: McpServerRecord[] }>("/mcp/servers"),

  createServer: (payload: McpServerPayload) =>
    api.post<McpServerRecord>("/mcp/servers", payload),

  updateServer: (serverId: string, patch: Partial<McpServerPayload>) =>
    api.patch<McpServerRecord>(`/mcp/servers/${serverId}`, patch),

  deleteServer: (serverId: string) =>
    api.delete<{ deleted: boolean }>(`/mcp/servers/${serverId}`),

  testServer: (serverId: string) =>
    api.post<McpOperationEnvelope>(`/mcp/servers/${serverId}/test`),

  listTools: (serverId: string) =>
    api.get<McpToolsResponse>(`/mcp/servers/${serverId}/tools`),

  invokeById: (serverId: string, payload: Omit<McpInvokeRequest, "server_id" | "server_name">) =>
    api.post<McpOperationEnvelope & { result?: unknown }>(
      `/mcp/servers/${serverId}/invoke`,
      payload,
    ),

  invoke: (payload: McpInvokeRequest) =>
    api.post<McpOperationEnvelope & { result?: unknown }>("/mcp/invoke", payload),
};
