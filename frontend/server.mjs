// QuantFlow 生产静态服务 + /api 反向代理（零依赖 Node 实现）
// 用法：node server.mjs  （监听 8080，/api 转发到 QF_BACKEND_URL 默认 http://127.0.0.1:8100）
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, request } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.QF_PORT || 8080);
const BACKEND_URL = process.env.QF_BACKEND_URL || "http://127.0.0.1:8100";
const root = join(dirname(fileURLToPath(import.meta.url)), "dist");
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
};

createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");

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
  res.writeHead(200, {
    "Content-Type": types[extname(file)] || "application/octet-stream",
    "Cache-Control": file.endsWith("index.html") ? "no-cache" : "public, max-age=31536000, immutable",
  });
  createReadStream(file).pipe(res);
}).listen(PORT, "0.0.0.0");

console.log(`QuantFlow frontend serving ${root} on :${PORT}, proxying /api -> ${BACKEND_URL}`);
