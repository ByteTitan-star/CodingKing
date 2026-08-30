from pathlib import Path

from coderking.evalkit.runner import EvalMetrics, write_reports


def test_write_reports(tmp_path: Path) -> None:
    rows = [
        EvalMetrics(
            task_id="demo",
            category="bug_fix",
            success=True,
            test_pass=True,
            iterations=4,
            repair_used=True,
            repair_count=1,
            tool_calls=6,
            prompt_tokens=10,
            completion_tokens=20,
            changed_files=["a.py"],
            first_test_result="fail",
            final_test_result="pass",
            diff="+ok\n",
            model="scripted",
        )
    ]
    json_path, md_path = write_reports(rows, tmp_path, extra={"note": "unit"})
    assert json_path.is_file()
    assert "task_success_rate" in json_path.read_text(encoding="utf-8")
    assert "demo" in md_path.read_text(encoding="utf-8")


def test_write_reports_redacts_secret_markers(tmp_path: Path) -> None:
    rows = [
        EvalMetrics(
            task_id="leak",
            category="bug_fix",
            success=True,
            test_pass=True,
            iterations=1,
            repair_used=False,
            repair_count=0,
            tool_calls=1,
            prompt_tokens=1,
            completion_tokens=1,
            changed_files=[".env"],
            first_test_result="ok",
            final_test_result="ok",
            diff="+API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n",
            model="scripted",
        )
    ]
    json_path, md_path = write_reports(rows, tmp_path, stem="scrubbed")
    text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in text
    assert "<redacted>" in text
