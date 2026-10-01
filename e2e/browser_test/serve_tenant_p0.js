// 本地 P0 回归静态服务：用构建产物 frontend/dist-tenant-p0 提供前端，并把 /api 反代到本地后端 :8000。
// 与 serve_dist.js 相同实现，仅 ROOT / PORT 不同（5173 已被 QA 占用，这里用 5178）。
// 未跟踪文件（不进 git），仅用于本地回归。
const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const ROOT = 'D:/工业元/数云_新质力/ziwi_project_SaaS/code/frontend/dist-tenant-p0';
const API = { host: '127.0.0.1', port: 8000 };
const PORT = 5178;

const MIME = {
  '.html': 'text/html', '.js': 'application/javascript', '.mjs': 'application/javascript',
  '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.map': 'application/json',
};

const server = http.createServer((req, res) => {
  const u = new URL(req.url, `http://localhost:${PORT}`);
  const p = decodeURIComponent(u.pathname);

  if (p.startsWith('/api')) {
    const opts = { host: API.host, port: API.port, path: req.url, method: req.method,
      headers: { ...req.headers, host: `localhost:${API.port}` } };
    const proxy = http.request(opts, (pres) => {
      res.writeHead(pres.statusCode, pres.headers);
      pres.pipe(res);
    });
    proxy.on('error', (e) => { res.writeHead(502); res.end('proxy error: ' + e.message); });
    req.pipe(proxy);
    return;
  }

  let filePath = path.join(ROOT, p === '/' ? 'index.html' : p);
  fs.stat(filePath, (err, st) => {
    if (err || !st.isFile()) {
      if (path.extname(p)) { res.writeHead(404); res.end('not found'); return; }
      filePath = path.join(ROOT, 'index.html');
    }
    fs.readFile(filePath, (err2, buf) => {
      if (err2) { res.writeHead(404); res.end('not found'); return; }
      const ext = path.extname(filePath).toLowerCase();
      res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
      res.end(buf);
    });
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[serve_tenant_p0] ${ROOT} -> http://127.0.0.1:${PORT} (/api -> ${API.host}:${API.port})`);
});
