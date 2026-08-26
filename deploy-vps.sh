#!/usr/bin/env bash

set -Eeuo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
WEB_SERVICE="frappe-web"

fail() {
	echo "ERROR: $*" >&2
	exit 1
}

echo "=========================================================="
echo " Lexocrates LPO & ERPNext production deployment"
echo "=========================================================="

command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is not installed."
[ -f .env ] || fail "Create .env from .env.example, replace every CHANGE_ME value, then rerun."

set -a
# shellcheck disable=SC1091
source .env
set +a

for variable in SITE_NAME DB_ROOT_PASSWORD ADMIN_PASSWORD; do
	value="${!variable:-}"
	[ -n "$value" ] || fail "$variable is required in .env."
	case "$value" in
		CHANGE_ME*|Secret*|admin|development.localhost|*.example.com)
			fail "$variable still contains a development/default value."
			;;
	esac
done

for variable in DB_ROOT_PASSWORD ADMIN_PASSWORD; do
	value="${!variable}"
	[ "${#value}" -ge 16 ] || fail "$variable must contain at least 16 characters."
done

[ "${DEVELOPER_MODE:-0}" = "0" ] || fail "DEVELOPER_MODE must be 0 for production."
mkdir -p sites logs

echo "[1/6] Validating and building the production stack..."
docker compose -f "$COMPOSE_FILE" config --quiet
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d mariadb redis-cache redis-queue clamav-updater

echo "[2/6] Waiting for MariaDB readiness..."
for attempt in $(seq 1 60); do
	if docker compose -f "$COMPOSE_FILE" exec -T mariadb \
		mysqladmin ping -h localhost -u root -p"$DB_ROOT_PASSWORD" --silent >/dev/null 2>&1; then
		break
	fi
	[ "$attempt" -lt 60 ] || fail "MariaDB did not become ready within 5 minutes."
	sleep 5
done

echo "[3/6] Starting application services..."
docker compose -f "$COMPOSE_FILE" up -d "$WEB_SERVICE" socketio scheduler worker-short worker-long

bench_exec() {
	docker compose -f "$COMPOSE_FILE" exec -T "$WEB_SERVICE" "$@"
}

echo "[4/6] Preparing common Frappe configuration and site..."
bench_exec bench set-config -g db_host mariadb
bench_exec bench set-config -g redis_cache redis://redis-cache:6379
bench_exec bench set-config -g redis_queue redis://redis-queue:6379
bench_exec bench set-config -g redis_socketio redis://redis-queue:6379
bench_exec bench set-config -g socketio_port 9000
bench_exec bench set-config -g default_site "$SITE_NAME"

if ! bench_exec test -f "sites/$SITE_NAME/site_config.json"; then
	bench_exec bench new-site "$SITE_NAME" \
		--admin-password "$ADMIN_PASSWORD" \
		--db-root-password "$DB_ROOT_PASSWORD" \
		--no-mariadb-socket
fi

echo "[5/6] Installing apps and applying migrations..."
for app in erpnext lex erpnext_custom; do
	if ! bench_exec bench --site "$SITE_NAME" list-apps --format text | grep -qx "$app"; then
		bench_exec bench --site "$SITE_NAME" install-app "$app"
	fi
done
bench_exec bench --site "$SITE_NAME" set-config developer_mode 0
bench_exec bench --site "$SITE_NAME" set-config allow_tests 0
bench_exec bench --site "$SITE_NAME" migrate
bench_exec bench --site "$SITE_NAME" enable-scheduler
bench_exec bench --site "$SITE_NAME" clear-cache

echo "[6/6] Restarting and checking service health..."
docker compose -f "$COMPOSE_FILE" restart "$WEB_SERVICE" socketio scheduler worker-short worker-long
docker compose -f "$COMPOSE_FILE" ps

echo "=========================================================="
echo " Deployment completed for https://$SITE_NAME"
echo " Configure host Nginx/Certbot before exposing the service."
echo "=========================================================="
