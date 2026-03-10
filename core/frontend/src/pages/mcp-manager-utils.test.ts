import { describe, expect, it } from "vitest";

import {
  buildMcpServerPayload,
  parseJsonObject,
  parseStringArrayCsv,
  type McpFormState,
} from "./mcp-manager-utils";

function baseForm(): McpFormState {
  return {
    name: "server-a",
    description: "desc",
    transport: "http",
    command: "",
    argsCsv: "",
    cwd: "",
    envJson: "{}",
    url: "https://example.com/mcp",
    headersJson: '{"Accept":"application/json"}',
    rpcPathsCsv: " /mcp, /sse ",
    oauthCredentialId: "",
  };
}

describe("mcp-manager-utils", () => {
  it("parses CSV string arrays", () => {
    expect(parseStringArrayCsv("a, b , ,c")).toEqual(["a", "b", "c"]);
  });

  it("parses JSON object values", () => {
    expect(parseJsonObject('{"x":1}', "headers")).toEqual({ x: 1 });
    expect(parseJsonObject("", "headers")).toEqual({});
  });

  it("rejects non-object JSON", () => {
    expect(() => parseJsonObject("[]", "headers")).toThrow(
      "headers must be a JSON object",
    );
  });

  it("builds HTTP payload", () => {
    const payload = buildMcpServerPayload(baseForm());
    expect(payload.transport).toBe("http");
    expect(payload.url).toBe("https://example.com/mcp");
    expect(payload.rpc_paths).toEqual(["/mcp", "/sse"]);
    expect(payload.headers).toEqual({ Accept: "application/json" });
  });

  it("builds stdio payload", () => {
    const form = baseForm();
    form.transport = "stdio";
    form.command = "uv";
    form.argsCsv = "run, mcp.py";
    form.cwd = "./tools";
    form.envJson = '{"LOG_LEVEL":"info"}';
    form.url = "";

    const payload = buildMcpServerPayload(form);
    expect(payload.transport).toBe("stdio");
    expect(payload.command).toBe("uv");
    expect(payload.args).toEqual(["run", "mcp.py"]);
    expect(payload.env).toEqual({ LOG_LEVEL: "info" });
  });

  it("rejects missing required fields", () => {
    const httpMissingUrl = baseForm();
    httpMissingUrl.url = "";
    expect(() => buildMcpServerPayload(httpMissingUrl)).toThrow(
      "url is required for http transport",
    );

    const stdioMissingCommand = baseForm();
    stdioMissingCommand.transport = "stdio";
    stdioMissingCommand.command = "";
    expect(() => buildMcpServerPayload(stdioMissingCommand)).toThrow(
      "command is required for stdio transport",
    );
  });
});
