#!/bin/sh
set -e

mkdir -p /etc/nginx/ssl

if [ ! -f /etc/nginx/ssl/nginx.crt ] || [ ! -f /etc/nginx/ssl/nginx.key ]; then
    echo "==> Generating self-signed SSL certificate for temporary Docker deployment..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/nginx.key \
        -out /etc/nginx/ssl/nginx.crt \
        -subj "/C=US/ST=State/L=City/O=Development/CN=development.localhost" \
        -addext "subjectAltName=DNS:development.localhost,DNS:localhost,IP:127.0.0.1"
    echo "==> SSL Certificate generated successfully."
fi

exec "$@"
