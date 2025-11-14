UV ?= uv
EDGE_MODE ?= nginx-terminate
HYPERCORN_CONFIG ?= ops/hypercorn.toml
HYPERCORN_CERT_FILE ?= /etc/ssl/live/mcp.example.com/fullchain.pem
HYPERCORN_KEY_FILE ?= /etc/ssl/live/mcp.example.com/privkey.pem
SMOKE_HOST ?= https://localhost
APP_SERVICE ?= hypercorn.service
NGINX_SERVICE ?= nginx.service

.PHONY: format lint types test run-hypercorn reload-hypercorn install-systemd smoke-h3 ci dev-up dev-down reload-nginx logs-app logs-nginx verify-h3

format:
	$(UV) run ruff format

lint:
	$(UV) run ruff check --fix

types:
	$(UV) run pyright --warnings --pythonversion=3.13
	$(UV) run pyrefly check

test:
	SKIP_GPU_WARMUP=1 $(UV) run pytest -q

dev-up: run-hypercorn

dev-down:
	- pkill -f "codeintel_rev.app.main:asgi" >/dev/null 2>&1 || true

run-hypercorn:
	EDGE_MODE=$(EDGE_MODE) \
	HYPERCORN_CONFIG=$(HYPERCORN_CONFIG) \
	HYPERCORN_CERT_FILE=$(HYPERCORN_CERT_FILE) \
	HYPERCORN_KEY_FILE=$(HYPERCORN_KEY_FILE) \
	$(UV) run bash ops/scripts/run_hypercorn.sh

reload-hypercorn:
	sudo systemctl reload $(APP_SERVICE) || sudo systemctl restart $(APP_SERVICE)

reload-nginx:
	bash ops/scripts/reload_nginx.sh

logs-app:
	sudo journalctl -u $(APP_SERVICE) -f

logs-nginx:
	sudo journalctl -u $(NGINX_SERVICE) -f

install-systemd:
	sudo install -D -m0755 ops/scripts/run_hypercorn.sh /opt/app/ops/scripts/run_hypercorn.sh
	sudo install -D -m0644 ops/systemd/hypercorn.service /etc/systemd/system/hypercorn.service
	sudo install -D -m0644 ops/systemd/nginx-pass-through.target /etc/systemd/system/nginx-pass-through.target
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(APP_SERVICE)

smoke-h3:
	bash ops/scripts/smoke_h3.sh $(SMOKE_HOST)

verify-h3: smoke-h3

ci: format lint types test
