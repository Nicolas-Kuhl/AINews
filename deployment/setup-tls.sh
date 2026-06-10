#!/usr/bin/env bash
#
# Put the AINews dashboard behind HTTPS.
#
# The app is currently served over plain HTTP on port 80, so all traffic —
# including the login session cookie — crosses the network in cleartext. This
# script terminates TLS at nginx and redirects HTTP to HTTPS.
#
# Two modes:
#
#   ./setup-tls.sh news.example.com you@example.com
#       Real certificate via Let's Encrypt (certbot). Requires the domain's
#       DNS A record to already point at this instance. This is the right
#       option for production.
#
#   ./setup-tls.sh
#       No domain → self-signed certificate. Encrypts the connection (fixes the
#       cleartext-cookie problem) but browsers will warn. Fine as an interim
#       while you're still on a bare IP; replace with the domain path later.
#
# Run on the EC2 instance with sudo privileges. Assumes the Amazon Linux layout
# created by aws-ec2-setup.sh (config at /etc/nginx/conf.d/ainews.conf).
#
set -euo pipefail

CONF=/etc/nginx/conf.d/ainews.conf
DOMAIN="${1:-}"
EMAIL="${2:-}"

if [ -n "$DOMAIN" ]; then
    echo "=== TLS via Let's Encrypt for $DOMAIN ==="
    if ! command -v certbot >/dev/null 2>&1; then
        sudo dnf install -y certbot python3-certbot-nginx \
            || sudo apt install -y certbot python3-certbot-nginx
    fi
    # Point server_name at the real domain so certbot can match the block.
    sudo sed -i "s/server_name _;/server_name $DOMAIN;/" "$CONF"
    sudo nginx -t && sudo systemctl reload nginx
    # certbot --nginx provisions the cert AND rewrites the config to add the
    # 443 server block and the 80 -> 443 redirect.
    if [ -n "$EMAIL" ]; then
        sudo certbot --nginx -d "$DOMAIN" --redirect --agree-tos -m "$EMAIL" --non-interactive
    else
        sudo certbot --nginx -d "$DOMAIN" --redirect
    fi
    echo "Done. Certbot installed a renewal timer; certs auto-renew."
    exit 0
fi

echo "=== Interim self-signed TLS (no domain) ==="
CERT_DIR=/etc/nginx/tls
sudo mkdir -p "$CERT_DIR"
if [ ! -f "$CERT_DIR/selfsigned.crt" ]; then
    sudo openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
        -keyout "$CERT_DIR/selfsigned.key" \
        -out "$CERT_DIR/selfsigned.crt" \
        -subj "/CN=ainews"
fi

# Rewrite the nginx config: redirect all HTTP to HTTPS, serve the app on 443.
sudo tee "$CONF" > /dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    ssl_certificate     /etc/nginx/tls/selfsigned.crt;
    ssl_certificate_key /etc/nginx/tls/selfsigned.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    location /rss {
        alias /opt/ainews/data;
        location ~ \.xml$ {
            add_header Content-Type application/rss+xml;
        }
    }
}
EOF

sudo nginx -t && sudo systemctl restart nginx
echo "Done. Dashboard now on https:// (self-signed — expect a browser warning)."
echo "Remember to also open port 443 in the instance's security group."
