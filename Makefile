.PHONY: check test steps steps-online eval

UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

check:
	$(UV) run ruff format .
	$(UV) run ruff check . --fix

test:
	$(UV) run pytest evals -m "not eval" -q

steps:
	$(UV) run pytest evals/synthetic -q

steps-online:
	@test -f .env || { echo "missing .env"; exit 1; }
	set -a && . ./.env && set +a && $(UV) run pytest evals/online/test_steps.py -m eval -q

eval:
	@test -f .env || { echo "missing .env — copy .env.template and fill in your keys"; exit 1; }
	set -a && . ./.env && set +a && $(UV) run pytest $(if $(EVAL),$(EVAL),evals/online) -m eval -s
