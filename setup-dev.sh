#!/usr/bin/env bash
# Automated Dev Environment Setup Script (Bash for Linux/macOS)
set -e

echo "=== Frappe v15 / ERPNext Local Dev Setup ==="

# Step 1: Check .env
if [ ! -f .env ]; then
  echo "[1/4] Copying .env.example to .env..."
  cp .env.example .env
  echo "Created .env file. Update secret credentials as appropriate."
else
  echo "[1/4] .env file already exists."
fi

# Step 2: Launch Docker Compose
echo "[2/4] Starting Docker containers..."
docker compose up -d --build

# Step 3: Wait for DB container health
echo "[3/4] Waiting for MariaDB health check..."
sleep 10

# Step 4: Status check
echo "[4/4] Container status:"
docker compose ps

echo "=== Setup Complete! ==="
echo "Execute interactive container shell:"
echo "  docker exec -it frappe-bench bash"
