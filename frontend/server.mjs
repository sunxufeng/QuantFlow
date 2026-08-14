// QuantFlow 生产静态服务 + /api 反向代理（零依赖 Node 实现）
// 用法：node server.mjs  （监听 8080，/api 转发到 QF_BACKEND_URL 默认 http://127.0.0.1:8100）
// 支持 /api/ws/* WebSocket 升级转发（运行状态实时推送）
import { createReadStream, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createServer, request } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.QF_PORT || 8080);
const BACKEND_URL = process.env.QF_BACKEND_URL || "http://127.0.0.1:8100";
const root = join(dirname(fileURLToPath(import.meta.url)), "dist");

// 读取前端构建号：每次发版都不同，用于把入口重定向到带构建号的专属路径，
// 保证浏览器/CDN 永远无法命中发版前的旧 index.html / 旧 bundle。
let BUILD_ID = "dev";
try {
  const v = JSON.parse(readFileSync(join(root, "version.json"), "utf8"));
  if (v && v.build) BUILD_ID = String(v.build);
} catch {
  // version.json 缺失时回退到 dist 内第一个 assets 子目录名（兜底）
  try {
    const assetsDir = join(root, "assets");
    const sub = readdirSync(assetsDir).find((d) => /^[A-Za-z0-9_-]+$/.test(d));
    if (sub) BUILD_ID = sub;
  } catch {}
}
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
};

const server = createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");

  // 缓存破坏（根治 setView is not defined / LLM 白屏）：
  // 裸根路径（无查询参数）一律 302 跳转到「带构建号的专属入口 /<BUILD_ID>/」。
  // 该路径每次发版都不同，浏览器/CDN 永远无法命中旧缓存；
  // 入口 index.html 与 bundle 均 no-store，后续请求始终回源取最新。
  // 带构建号路径本身（/BUILD_ID/ 或 /BUILD_ID）直接返回 index.html，避免死循环。
  if (url.pathname === "/" && !url.search) {
    res.writeHead(302, { Location: "/" + BUILD_ID + "/", "Cache-Control": "no-store" });
    res.end();
    return;
  }
  if (url.pathname === "/" + BUILD_ID || url.pathname === "/" + BUILD_ID + "/") {
    const file = join(root, "index.html");
    res.writeHead(200, { "Content-Type": types[".html"], "Cache-Control": "no-store" });
    createReadStream(file).pipe(res);
    return;
  }

  // /api/* 反向代理到后端
  if (url.pathname.startsWith("/api/")) {
    const upstream = new URL(url.pathname + url.search, BACKEND_URL);
    const proxy = request(upstream, { method: req.method, headers: req.headers }, (response) => {
      res.writeHead(response.statusCode || 502, response.headers);
      response.pipe(res);
    });
    proxy.on("error", () => { res.writeHead(502); res.end("Bad Gateway"); });
    req.pipe(proxy);
    return;
  }

  // 静态资源，SPA 路由回退到 index.html
  const relative = decodeURIComponent(url.pathname).replace(/^\/+/, "");
  let file = normalize(join(root, relative));
  if (!file.startsWith(root) || !existsSync(file) || statSync(file).isDirectory()) {
    file = join(root, "index.html");
  }
  // version.json 携带前端构建号，供看门狗比对，必须 no-store（禁止 CDN/浏览器缓存）以免误判陈旧
  const isNoStore = file.endsWith("index.html") || file.endsWith("version.json");
  res.writeHead(200, {
    "Content-Type": types[extname(file)] || "application/octet-stream",
    "Cache-Control": isNoStore ? "no-store" : "public, max-age=31536000, immutable",
  });
  createReadStream(file).pipe(res);
});

// WebSocket 升级转发（/api/ws/* → 后端）
server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url, "http://localhost");
  if (!url.pathname.startsWith("/api/ws/")) {
    socket.destroy();
    return;
  }
  const upstream = new URL(url.pathname + url.search, BACKEND_URL);
  const proxy = request(upstream, {
    method: "GET",
    headers: {
      ...req.headers,
      host: upstream.host,
      connection: "Upgrade",
      upgrade: "websocket",
    },
  });
  proxy.on("upgrade", (res, upstreamSocket, upstreamHead) => {
    upstreamSocket.on("error", () => socket.destroy());
    socket.on("error", () => upstreamSocket.destroy());
    // 客户端已发出的首个帧数据（head）转发给上游
    if (head?.length) upstreamSocket.write(head);
    // 回写 101 握手响应（原样转发上游头，含 Sec-WebSocket-Extensions 等）
    const hdrs = Object.entries(res.headers || {})
      .filter(([k]) => !["connection", "upgrade", "transfer-encoding"].includes(k))
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}\r\n`)
      .join("");
    socket.write("HTTP/1.1 101 Switching Protocols\r\n" +
      `Upgrade: ${res.headers.upgrade || "websocket"}\r\n` +
      "Connection: Upgrade\r\n" +
      hdrs + "\r\n");
    // 上游已发出的首个帧数据转发给客户端
    if (upstreamHead?.length) socket.write(upstreamHead);
    // 双向管道
    upstreamSocket.pipe(socket);
    socket.pipe(upstreamSocket);
  });
  proxy.on("error", () => socket.destroy());
  proxy.end();
});

server.listen(PORT, "0.0.0.0");

console.log(`QuantFlow frontend serving ${root} on :${PORT}, proxying /api -> ${BACKEND_URL}`);
