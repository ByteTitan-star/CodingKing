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
