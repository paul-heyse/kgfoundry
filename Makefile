UV ?= uv
H3_HOST ?= mcp.example.com

.PHONY: format lint types test run-hypercorn reload-hypercorn install-systemd verify-h3 ci

format:
	$(UV) run ruff format

lint:
	$(UV) run ruff check --fix

types:
	$(UV) run pyright --warnings --pythonversion=3.13
	$(UV) run pyrefly check

test:
	SKIP_GPU_WARMUP=1 $(UV) run pytest -q

run-hypercorn:
	$(UV) run hypercorn --config ops/hypercorn/hypercorn.toml codeintel_rev.app.main:asgi

reload-hypercorn:
	sudo systemctl reload hypercorn-codeintel.service || sudo systemctl restart hypercorn-codeintel.service

install-systemd:
	sudo install -D -m0644 ops/systemd/hypercorn-codeintel.service /etc/systemd/system/hypercorn-codeintel.service
	sudo install -D -m0644 ops/systemd/nginx.service.d/override.conf /etc/systemd/system/nginx.service.d/override.conf
	sudo systemctl daemon-reload
	sudo systemctl enable --now hypercorn-codeintel.service

verify-h3:
	curl --http3-only -I https://$(H3_HOST)/readyz

ci: format lint types test
