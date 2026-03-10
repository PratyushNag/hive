import { afterEach, describe, expect, it, vi } from "vitest";

import { mcpApi } from "./mcp";

function mockJsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

describe("mcpApi", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls listServers with GET /api/mcp/servers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockJsonResponse({ servers: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await mcpApi.listServers();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/mcp/servers",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("calls createServer with POST body", async () => {
    const payload = { name: "fast", transport: "http" as const, url: "https://x" };
    const fetchMock = vi.fn().mockResolvedValue(mockJsonResponse({ id: "1", ...payload }));
    vi.stubGlobal("fetch", fetchMock);

    await mcpApi.createServer(payload);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/mcp/servers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
      }),
    );
  });

  it("calls updateServer with PATCH", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockJsonResponse({ id: "1", name: "new" }));
    vi.stubGlobal("fetch", fetchMock);

    await mcpApi.updateServer("1", { name: "new" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/mcp/servers/1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "new" }) }),
    );
  });

  it("calls invoke endpoint with payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockJsonResponse({ ok: true, status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await mcpApi.invoke({
      server_name: "fast",
      tool_name: "ping",
      tool_arguments: { value: 1 },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/mcp/invoke",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          server_name: "fast",
          tool_name: "ping",
          tool_arguments: { value: 1 },
        }),
      }),
    );
  });
});
