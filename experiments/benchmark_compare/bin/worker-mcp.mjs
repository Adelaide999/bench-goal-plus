// Use the installed MCP SDK; all authorization and response filtering stay in the host proxy.
import { createRequire } from "node:module";
import { createConnection } from "node:net";
import { join } from "node:path";

const require = createRequire(join(process.env.BENCH_GOAL_PLUS_PACKAGE, "assets/pi/package.json"));
const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { ListToolsRequestSchema, CallToolRequestSchema } = require("@modelcontextprotocol/sdk/types.js");
const MAX_RESPONSE_BYTES = 16 * 1024 * 1024;
const MAX_REQUEST_BYTES = 1024 * 1024;

function request(payload) {
  const encoded = Buffer.from(JSON.stringify(payload) + "\n");
  if (encoded.length > MAX_REQUEST_BYTES) throw new Error("worker request is too large");
  return new Promise((resolve, reject) => {
    const socket = createConnection(process.env.BENCH_GOAL_PLUS_PI_TOOL_SOCKET);
    const chunks = [];
    let size = 0;
    socket.on("connect", () => socket.end(encoded));
    socket.on("error", reject);
    socket.on("data", chunk => {
      size += chunk.length;
      if (size > MAX_RESPONSE_BYTES) socket.destroy(new Error("worker response is too large"));
      else chunks.push(chunk);
    });
    socket.on("end", () => {
      try {
        const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (result.ok !== true) throw new Error("worker tool response is unavailable");
        resolve(result.result);
      } catch (error) { reject(error); }
    });
  });
}

const server = new Server({ name: "bench-goal-plus-worker", version: "1" }, { capabilities: { tools: {} } });
server.setRequestHandler(ListToolsRequestSchema, () => request({ tool: "host_mcp_manifest", args: {} }));
server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
  try {
    const result = await request({
      tool: params.name, args: params.arguments ?? {},
      native_session_id: params._meta?.threadId ?? null,
    });
    return { content: [{ type: "text", text: JSON.stringify(result) }] };
  } catch {
    return { isError: true, content: [{ type: "text", text: "worker tool response is unavailable" }] };
  }
});
await server.connect(new StdioServerTransport());
