FROM nginxinc/nginx-unprivileged:alpine

RUN printf '%s\n' \
  '<!doctype html>' \
  '<html lang="ja">' \
  '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rental Server</title></head>' \
  '<body style="font-family:system-ui,sans-serif;max-width:760px;margin:80px auto;padding:0 24px;color:#172033">' \
  '<div style="border:1px solid #dfe5ec;border-radius:14px;padding:28px;background:#fff">' \
  '<h1>Nginx Server</h1><p>Nginx Web サーバーは正常に稼働しています。</p>' \
  '</div></body></html>' \
  > /usr/share/nginx/html/index.html

EXPOSE 8080
