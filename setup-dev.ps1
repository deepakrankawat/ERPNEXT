# Automated Dev Environment Setup Script (PowerShell for Windows)
# Run this script to bootstrap your local Frappe v15 development container.

Write-Host "--- Frappe v15 / ERPNext Local Dev Setup ---" -ForegroundColor Cyan

# Step 1: Ensure .env exists
if (-not (Test-Path ".env")) {
    Write-Host "[1/4] Creating .env file from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env! Please review and update credentials if needed." -ForegroundColor Green
} else {
    Write-Host "[1/4] .env file already exists." -ForegroundColor Green
}

# Step 2: Build and Start Containers
Write-Host "[2/4] Starting Docker Containers..." -ForegroundColor Yellow
docker compose up -d --build

# Step 3: Wait for DB Health
Write-Host "[3/4] Waiting for MariaDB container to be healthy..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Step 4: Show status
Write-Host "[4/4] Container status:" -ForegroundColor Yellow
docker compose ps

Write-Host "--- Setup Complete! ---" -ForegroundColor Green
Write-Host "Next step: Run setup inside bench container:" -ForegroundColor Cyan
Write-Host "  docker exec -it frappe-bench bash" -ForegroundColor White
Write-Host "  bench new-site development.localhost --admin-password admin --db-root-password SecretDbRootPassword123!" -ForegroundColor White
