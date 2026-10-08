from jobhunt.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("db", "seed", "scrape", "doctor", "tick", "profile", "match", "serve", "mcp"):
        assert name in result.stdout
