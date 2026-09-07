import http from "node:http";
import net from "node:net";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const root = dirname(fileURLToPath(import.meta.url));
const listenPort = Number(process.env.CAPTURE_HTTP_PORT || 6080);
const vncPort = Number(process.env.CAPTURE_VNC_PORT || 5902);

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    let file;
    if (url.pathname === "/") file = join(root, "index.html");
    else if (url.pathname.startsWith("/novnc/")) {
      const relative = url.pathname.slice("/novnc/".length);
      if (relative.includes("..")) throw new Error("invalid path");
      file = join(root, "node_modules/@novnc/novnc", relative);
    } else throw new Error("not found");
    const data = await readFile(file);
    response.writeHead(200, { "Content-Type": file.endsWith(".js") ? "text/javascript" : "text/html" });
    response.end(data);
  } catch {
    response.writeHead(404);
    response.end("not found");
  }
});
const websocket = new WebSocketServer({ server, path: "/websockify" });
websocket.on("connection", (client) => {
  const vnc = net.createConnection({ host: "127.0.0.1", port: vncPort });
  client.on("message", (data) => vnc.write(data));
  vnc.on("data", (data) => client.send(data));
  client.on("close", () => vnc.destroy());
  vnc.on("close", () => client.close());
  vnc.on("error", () => client.close());
});

server.listen(listenPort, "127.0.0.1", () => {
  console.log(`capture server: http://127.0.0.1:${listenPort}`);
});
