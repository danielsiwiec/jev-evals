.PHONY: check test unit unit-online e2e eval

UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

check:
	$(UV) run ruff format .
	$(UV) run ruff check . --fix

test:
	$(UV) run pytest evals -m "not eval" -q

unit:
	$(UV) run pytest evals/offline -q

unit-online:
	@test -f .env || { echo "missing .env"; exit 1; }
	set -a && . ./.env && set +a && $(UV) run pytest evals/online/test_unit.py -m eval -q

e2e eval:
	@test -f .env || { echo "missing .env — copy .env.template and fill in your keys"; exit 1; }
	set -a && . ./.env && set +a && $(UV) run pytest $(if $(EVAL),$(EVAL),evals/online/test_download_e2e.py evals/online/test_refinance_e2e.py) -m eval -s
