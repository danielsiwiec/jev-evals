.PHONY: check test eval

check:
	uv run ruff format .
	uv run ruff check . --fix

test:
	uv run pytest evals -m "not eval" -q

eval:
	uv run pytest evals -m eval -s
