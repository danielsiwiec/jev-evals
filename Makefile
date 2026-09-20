.PHONY: check test eval browser

UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

check:
	$(UV) run ruff format .
	$(UV) run ruff check . --fix

test:
	$(UV) run pytest evals -m "not eval" -q

browser:
	@curl -s -m 2 http://localhost:9222/json/version >/dev/null 2>&1 && echo "chrome already on :9222" || ( \
	  echo "starting chrome on :9222 (throwaway profile)"; \
	  nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
	    --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-eval \
	    --no-first-run --no-default-browser-check about:blank >/dev/null 2>&1 & \
	  until curl -s -m 2 http://localhost:9222/json/version >/dev/null 2>&1; do sleep 0.5; done; \
	  echo "chrome up" )

eval: browser
	@test -f .env || { echo "missing .env — copy .env.template and fill in your keys"; exit 1; }
	set -a && . ./.env && set +a && $(UV) run pytest $(if $(EVAL),$(EVAL),evals) -m eval -s
