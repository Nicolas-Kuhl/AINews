#!/usr/bin/env bash
# Adds the /videos/ static location (episode MP4s + podcast feed.xml) to the
# nginx HTTPS server block. Idempotent: safe to run repeatedly.
set -euo pipefail

CONF="/etc/nginx/conf.d/ainews.conf"

if grep -q "location /videos/" "$CONF"; then
    echo "/videos/ location already present in $CONF"
    exit 0
fi

# Insert into the TLS server block, right after its server_name line.
sudo awk '
    /listen 443/ { in_tls = 1 }
    { print }
    in_tls && /server_name/ && !done {
        print "";
        print "    # Episode videos + podcast RSS feed (public)";
        print "    location /videos/ {";
        print "        alias /opt/ainews/data/videos/;";
        print "        autoindex off;";
        print "    }";
        done = 1
    }
' "$CONF" | sudo tee "${CONF}.new" > /dev/null
sudo mv "${CONF}.new" "$CONF"

sudo nginx -t
sudo systemctl reload nginx
echo "/videos/ location added and nginx reloaded"
