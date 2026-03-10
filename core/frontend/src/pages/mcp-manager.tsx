import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { mcpApi } from "@/api/mcp";
import type { McpOperationEnvelope, McpServerRecord } from "@/api/types";
import TopBar from "@/components/TopBar";
import {
  buildMcpServerPayload,
  type McpFormState,
} from "@/pages/mcp-manager-utils";

function defaultForm(): McpFormState {
  return {
    name: "",
    description: "",
    transport: "http",
    command: "",
    argsCsv: "",
    cwd: "",
    envJson: "{}",
    url: "",
    headersJson: "{\n  \"Accept\": \"application/json, text/event-stream\"\n}",
    rpcPathsCsv: "",
    oauthCredentialId: "",
  };
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function McpManagerPage() {
  const navigate = useNavigate();

  const [servers, setServers] = useState<McpServerRecord[]>([]);
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState<McpFormState>(defaultForm());
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [operationResult, setOperationResult] = useState<McpOperationEnvelope | null>(null);
  const [tools, setTools] = useState<Array<Record<string, unknown>>>([]);
  const [selectedTool, setSelectedTool] = useState<string>("");
  const [toolArgs, setToolArgs] = useState<string>("{}");
  const [invokeResult, setInvokeResult] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const selectedServer = useMemo(
    () => servers.find((server) => server.id === selectedServerId) || null,
    [servers, selectedServerId],
  );

  const loadServers = async (preferServerId?: string | null) => {
    const response = await mcpApi.listServers();
    setServers(response.servers);
    if (preferServerId) {
      const found = response.servers.find((server) => server.id === preferServerId);
      setSelectedServerId(found ? found.id : response.servers[0]?.id ?? null);
      return;
    }
    if (!selectedServerId && response.servers.length > 0) {
      setSelectedServerId(response.servers[0].id);
    }
    if (response.servers.length === 0) {
      setSelectedServerId(null);
    }
  };

  useEffect(() => {
    loadServers().catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to load MCP servers: ${msg}`);
    });
  }, []);

  useEffect(() => {
    if (!selectedServer || isEditing) {
      return;
    }
    setForm({
      name: selectedServer.name,
      description: selectedServer.description || "",
      transport: selectedServer.transport,
      command: selectedServer.command || "",
      argsCsv: (selectedServer.args || []).join(", "),
      cwd: selectedServer.cwd || "",
      envJson: pretty(selectedServer.env || {}),
      url: selectedServer.url || "",
      headersJson: pretty(selectedServer.headers || {}),
      rpcPathsCsv: (selectedServer.rpc_paths || []).join(", "),
      oauthCredentialId: selectedServer.oauth_credential_id || "",
    });
  }, [selectedServer, isEditing]);

  const handleNew = () => {
    setIsEditing(false);
    setSelectedServerId(null);
    setForm(defaultForm());
    setTools([]);
    setOperationResult(null);
    setInvokeResult(null);
    setInfo("Creating a new MCP server record");
    setError(null);
  };

  const handleSelectServer = (serverId: string) => {
    setSelectedServerId(serverId);
    setIsEditing(false);
    setOperationResult(null);
    setInvokeResult(null);
    setTools([]);
    setError(null);
    setInfo(null);
  };

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const payload = buildMcpServerPayload(form);
      if (selectedServerId) {
        await mcpApi.updateServer(selectedServerId, payload);
        setInfo("MCP server updated");
        await loadServers(selectedServerId);
      } else {
        const created = await mcpApi.createServer(payload);
        setInfo("MCP server created");
        await loadServers(created.id);
      }
      setIsEditing(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedServerId) {
      return;
    }
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await mcpApi.deleteServer(selectedServerId);
      setInfo("MCP server deleted");
      setTools([]);
      setOperationResult(null);
      setInvokeResult(null);
      await loadServers();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleTest = async () => {
    if (!selectedServerId) {
      return;
    }
    setBusy(true);
    setError(null);
    setInvokeResult(null);
    try {
      const result = await mcpApi.testServer(selectedServerId);
      setOperationResult(result);
      setInfo(`Test status: ${result.status}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleLoadTools = async () => {
    if (!selectedServerId) {
      return;
    }
    setBusy(true);
    setError(null);
    setInvokeResult(null);
    try {
      const result = await mcpApi.listTools(selectedServerId);
      setOperationResult(result);
      const nextTools = result.tools || [];
      setTools(nextTools);
      setSelectedTool(
        (nextTools.find((tool) => typeof tool.name === "string")?.name as string) || "",
      );
      setInfo(`Loaded ${nextTools.length} tools`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleInvoke = async () => {
    if (!selectedTool || !selectedServer) {
      setError("Select a server and tool first");
      return;
    }

    let parsedArgs: Record<string, unknown>;
    try {
      const parsed = JSON.parse(toolArgs || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Tool arguments must be a JSON object");
      }
      parsedArgs = parsed as Record<string, unknown>;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const result = await mcpApi.invoke({
        server_id: selectedServer.id,
        tool_name: selectedTool,
        tool_arguments: parsedArgs,
      });
      setOperationResult(result);
      setInvokeResult(result.result ?? null);
      setInfo(`Invoke status: ${result.status}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <TopBar />

      <div className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-foreground">MCP Manager</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Centralized MCP server CRUD, test, tool discovery, and manual invoke.
            </p>
          </div>
          <button
            onClick={() => navigate("/")}
            className="px-3 py-2 rounded-lg border border-border/60 text-sm text-muted-foreground hover:text-foreground"
          >
            Back
          </button>
        </div>

        {error && <div className="mb-4 text-sm text-destructive">{error}</div>}
        {info && <div className="mb-4 text-sm text-emerald-600">{info}</div>}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="rounded-xl border border-border/60 bg-card/40 p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Servers</h2>
              <button
                onClick={handleNew}
                className="px-2 py-1 text-xs rounded border border-border/60 hover:border-primary/40"
              >
                New
              </button>
            </div>
            <div className="space-y-2 max-h-[50vh] overflow-auto">
              {servers.length === 0 && (
                <p className="text-xs text-muted-foreground">No servers configured yet.</p>
              )}
              {servers.map((server) => (
                <button
                  key={server.id}
                  onClick={() => handleSelectServer(server.id)}
                  className={`w-full text-left px-3 py-2 rounded border text-xs transition-colors ${
                    selectedServerId === server.id
                      ? "border-primary/50 bg-primary/5 text-foreground"
                      : "border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/30"
                  }`}
                >
                  <div className="font-medium">{server.name}</div>
                  <div>{server.transport}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-card/40 p-4 lg:col-span-2">
            <h2 className="text-sm font-semibold mb-3">{selectedServerId ? "Edit Server" : "Create Server"}</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <label className="flex flex-col gap-1">
                <span>Name</span>
                <input
                  value={form.name}
                  onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                  className="px-3 py-2 rounded border border-border/60 bg-background"
                />
              </label>

              <label className="flex flex-col gap-1">
                <span>Transport</span>
                <select
                  value={form.transport}
                  onChange={(e) => setForm((prev) => ({ ...prev, transport: e.target.value as "stdio" | "http" }))}
                  className="px-3 py-2 rounded border border-border/60 bg-background"
                >
                  <option value="http">http</option>
                  <option value="stdio">stdio</option>
                </select>
              </label>

              <label className="flex flex-col gap-1 md:col-span-2">
                <span>Description</span>
                <input
                  value={form.description}
                  onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                  className="px-3 py-2 rounded border border-border/60 bg-background"
                />
              </label>

              <label className="flex flex-col gap-1 md:col-span-2">
                <span>OAuth Credential ID (optional)</span>
                <input
                  value={form.oauthCredentialId}
                  onChange={(e) => setForm((prev) => ({ ...prev, oauthCredentialId: e.target.value }))}
                  className="px-3 py-2 rounded border border-border/60 bg-background"
                />
              </label>

              {form.transport === "http" ? (
                <>
                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>URL</span>
                    <input
                      value={form.url}
                      onChange={(e) => setForm((prev) => ({ ...prev, url: e.target.value }))}
                      className="px-3 py-2 rounded border border-border/60 bg-background"
                    />
                  </label>

                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>RPC Paths (comma separated)</span>
                    <input
                      value={form.rpcPathsCsv}
                      onChange={(e) => setForm((prev) => ({ ...prev, rpcPathsCsv: e.target.value }))}
                      className="px-3 py-2 rounded border border-border/60 bg-background"
                    />
                  </label>

                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>Headers JSON</span>
                    <textarea
                      value={form.headersJson}
                      onChange={(e) => setForm((prev) => ({ ...prev, headersJson: e.target.value }))}
                      rows={5}
                      className="px-3 py-2 rounded border border-border/60 bg-background font-mono text-xs"
                    />
                  </label>
                </>
              ) : (
                <>
                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>Command</span>
                    <input
                      value={form.command}
                      onChange={(e) => setForm((prev) => ({ ...prev, command: e.target.value }))}
                      className="px-3 py-2 rounded border border-border/60 bg-background"
                    />
                  </label>

                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>Args (comma separated)</span>
                    <input
                      value={form.argsCsv}
                      onChange={(e) => setForm((prev) => ({ ...prev, argsCsv: e.target.value }))}
                      className="px-3 py-2 rounded border border-border/60 bg-background"
                    />
                  </label>

                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>CWD</span>
                    <input
                      value={form.cwd}
                      onChange={(e) => setForm((prev) => ({ ...prev, cwd: e.target.value }))}
                      className="px-3 py-2 rounded border border-border/60 bg-background"
                    />
                  </label>

                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span>Env JSON</span>
                    <textarea
                      value={form.envJson}
                      onChange={(e) => setForm((prev) => ({ ...prev, envJson: e.target.value }))}
                      rows={5}
                      className="px-3 py-2 rounded border border-border/60 bg-background font-mono text-xs"
                    />
                  </label>
                </>
              )}
            </div>

            <div className="flex flex-wrap gap-2 mt-4">
              <button
                onClick={handleSave}
                disabled={busy}
                className="px-3 py-2 rounded bg-primary text-primary-foreground text-sm disabled:opacity-60"
              >
                {selectedServerId ? "Save Changes" : "Create Server"}
              </button>
              <button
                onClick={() => setIsEditing((prev) => !prev)}
                className="px-3 py-2 rounded border border-border/60 text-sm"
              >
                {isEditing ? "Cancel Edit" : "Edit Mode"}
              </button>
              <button
                onClick={handleDelete}
                disabled={!selectedServerId || busy}
                className="px-3 py-2 rounded border border-destructive/40 text-destructive text-sm disabled:opacity-40"
              >
                Delete
              </button>
              <button
                onClick={handleTest}
                disabled={!selectedServerId || busy}
                className="px-3 py-2 rounded border border-border/60 text-sm disabled:opacity-40"
              >
                Test
              </button>
              <button
                onClick={handleLoadTools}
                disabled={!selectedServerId || busy}
                className="px-3 py-2 rounded border border-border/60 text-sm disabled:opacity-40"
              >
                Load Tools
              </button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <div className="rounded-xl border border-border/60 bg-card/40 p-4">
            <h2 className="text-sm font-semibold mb-2">Operation Result</h2>
            <pre className="text-xs bg-background border border-border/60 rounded p-3 overflow-auto max-h-72">
              {pretty(operationResult || { status: "idle" })}
            </pre>
          </div>

          <div className="rounded-xl border border-border/60 bg-card/40 p-4">
            <h2 className="text-sm font-semibold mb-2">Tool Runner</h2>
            <div className="space-y-2 text-sm">
              <label className="flex flex-col gap-1">
                <span>Tool</span>
                <select
                  value={selectedTool}
                  onChange={(e) => setSelectedTool(e.target.value)}
                  className="px-3 py-2 rounded border border-border/60 bg-background"
                >
                  <option value="">Select a tool</option>
                  {tools.map((tool, idx) => (
                    <option key={`${tool.name || "tool"}-${idx}`} value={String(tool.name || "")}>{String(tool.name || "")}</option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span>Arguments JSON</span>
                <textarea
                  value={toolArgs}
                  onChange={(e) => setToolArgs(e.target.value)}
                  rows={6}
                  className="px-3 py-2 rounded border border-border/60 bg-background font-mono text-xs"
                />
              </label>

              <button
                onClick={handleInvoke}
                disabled={!selectedServer || !selectedTool || busy}
                className="px-3 py-2 rounded bg-primary text-primary-foreground text-sm disabled:opacity-40"
              >
                Invoke Tool
              </button>
            </div>

            <h3 className="text-xs font-semibold mt-4 mb-2">Invoke Result</h3>
            <pre className="text-xs bg-background border border-border/60 rounded p-3 overflow-auto max-h-48">
              {pretty(invokeResult || { status: "idle" })}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
