import os

from litreview import cli
from litreview.records import Record


def test_select_applies_abstract_filter_before_limit():
    records = [Record(id=f"r{i}", title="t", abstract="" if i % 2 else "a", year="2024") for i in range(10)]
    selected = cli.select_records(records, since="", limit=3, require_abstract=True)
    assert [r.id for r in selected] == ["r0", "r2", "r4"]


def test_since_compares_full_date_and_keeps_unknown_dates():
    records = [Record(id="old", title="t", abstract="a", date="2024-03-01", year="2024"),
               Record(id="new", title="t", abstract="a", date="2024-09-01", year="2024"),
               Record(id="unknown", title="t", abstract="a")]
    selected = cli.select_records(records, since="2024-06-01", limit=0, require_abstract=True)
    assert [r.id for r in selected] == ["new", "unknown"]


def test_env_loaded_from_repo_root_and_theme_dir(tmp_path, monkeypatch):
    theme = tmp_path / "themes" / "t"
    theme.mkdir(parents=True)
    (tmp_path / ".env").write_text("ROOT_ONLY_KEY=root\nSHARED_KEY=root\n")
    (theme / ".env").write_text("SHARED_KEY=theme\n")
    monkeypatch.chdir(tmp_path)
    for k in ("ROOT_ONLY_KEY", "SHARED_KEY"):
        monkeypatch.delenv(k, raising=False)
    cli.load_env(str(theme / "config.yaml"))
    assert os.environ["ROOT_ONLY_KEY"] == "root"
    assert os.environ["SHARED_KEY"] == "theme"  # 主题目录更具体，优先
