const http = require('http');

const port = Number(process.env.PORT || 3000);
const name = process.env.RENTAL_SERVER_NAME || 'rental-server';
const plan = process.env.RENTAL_PLAN || 'free';

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200, {'Content-Type': 'application/json; charset=utf-8'});
    res.end(JSON.stringify({ok: true, service: 'rental-tenant-node'}));
    return;
  }

  res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
  res.end(`<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rental Server</title><style>body{font-family:system-ui,sans-serif;max-width:760px;margin:80px auto;padding:0 24px;color:#172033}.box{border:1px solid #dfe5ec;border-radius:14px;padding:28px;background:#fff}h1{margin-top:0}small{color:#667085}</style></head><body><div class="box"><h1>${name}</h1><p>Node.js Web サーバーは正常に稼働しています。</p><small>plan: ${plan}</small></div></body></html>`);
});

server.listen(port, '0.0.0.0', () => {
  console.log(`tenant node server listening on ${port}`);
});
