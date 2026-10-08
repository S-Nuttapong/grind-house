import shutil
from pathlib import Path

from jobhunt.fit.migrate_vault import date_from_period, humanize_kind, migrate_vault

_LEGACY = Path(__file__).resolve().parents[1] / "fixtures" / "bank_legacy"


def test_humanize_kind_and_period_end() -> None:
    from datetime import date

    assert humanize_kind("page-experience") == "Page Experience"
    assert humanize_kind(None) == "General"
    assert humanize_kind("") == "General"
    assert date_from_period("2025-08 – 2025-09", date(2026, 1, 1)) == date(2025, 9, 30)
    assert date_from_period("2024-01 – 2024-02", date(2026, 1, 1)) == date(2024, 2, 29)
    assert date_from_period("2021 – 2023", date(2026, 1, 1)) == date(2023, 12, 31)
    assert date_from_period("2023-10 – 2024", date(2026, 1, 1)) == date(2024, 12, 31)
    assert date_from_period("2020", date(2026, 1, 1)) == date(2020, 12, 31)
    assert date_from_period("2024-01 – present", date(2026, 1, 1)) == date.today()
    assert date_from_period("nope", date(2026, 10, 8)) == date(2026, 10, 8)


def test_dry_run_does_not_touch_files(tmp_path: Path) -> None:
    bank = _copy_legacy(tmp_path)
    original = (bank / "Entries" / "BB-001 Shipped payments.md").read_text()
    changes = migrate_vault(bank, write=False, backup_root=tmp_path / "backups")
    assert {change.action for change in changes} == {"rewrite"}
    assert (bank / "Entries" / "BB-001 Shipped payments.md").read_text() == original
    assert not (tmp_path / "backups").exists()


def test_write_backs_up_preserves_body_and_is_idempotent(tmp_path: Path) -> None:
    bank = _copy_legacy(tmp_path / "vault")
    original = (bank / "Entries" / "BB-001 Shipped payments.md").read_text()
    body = original.split("---\n", 2)[2]
    backups = tmp_path / "backups"

    first = migrate_vault(bank, write=True, backup_root=backups)
    assert all(change.action == "rewrite" for change in first)
    rewritten = (bank / "Entries" / "BB-001 Shipped payments.md").read_text()
    assert rewritten.split("---\n", 2)[2] == body
    assert "confidential:" not in rewritten.split("---\n", 2)[1]
    assert "key: Page Experience" in rewritten
    assert "key: General" in rewritten
    assert "date: '2023-06-30'" in rewritten or "date: 2023-06-30" in rewritten

    copied = list(backups.glob("*/Entries/BB-001 Shipped payments.md"))
    assert len(copied) == 1
    assert copied[0].read_text() == original

    second = migrate_vault(bank, write=True, backup_root=backups)
    assert {change.action for change in second} == {"skip"}
    assert (bank / "Entries" / "BB-001 Shipped payments.md").read_text() == rewritten
    assert len(list(backups.glob("*/Entries"))) == 1


def _copy_legacy(destination: Path) -> Path:
    bank = destination / "bank"
    shutil.copytree(_LEGACY, bank)
    return bank
