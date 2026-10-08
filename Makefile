.PHONY: check jh

# The check the plan requires after every task.
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy jobhunt
	uv run pytest -q

# Usage: make jh ARGS="doctor"
jh:
	op run --env-file=.env.tpl -- uv run jobhunt $(ARGS)
