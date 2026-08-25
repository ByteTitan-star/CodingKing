"""Browser E2E against Vite + FastAPI. Does not print secrets."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = "http://localhost:5173"


def _copy_bugfix() -> Path:
    dest = Path(tempfile.mkdtemp(prefix="coderking-web-e2e-")) / "repo"
    shutil.copytree(ROOT / "eval" / "tasks" / "bug_fix" / "add" / "repo", dest)
    return dest


def _fill_and_create(page, repo: Path, prompt: str) -> None:  # noqa: ANN001
    page.locator("[data-testid=repo-input]").fill(str(repo))
    page.locator("[data-testid=prompt-input]").fill(prompt)
    page.locator("[data-testid=test-command-input]").fill("python -m pytest -q")
    box = page.locator("[data-testid=auto-approve]")
    if not box.is_checked():
        box.check()
    page.locator("[data-testid=create-task]").click()


def main() -> None:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    coding_repo = _copy_bugfix()
    stop_repo = _copy_bugfix()
    out_dir = ROOT / "eval" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(WEB, wait_until="networkidle")
            checks["page_open"] = "CODERKING" in page.content()

            _fill_and_create(
                page,
                coding_repo,
                "Fix add() so it returns the sum of two integers. Do not change tests.",
            )
            page.wait_for_selector("[data-testid=task-status]", timeout=15_000)
            page.wait_for_function(
                """() => {
                  const s = document.querySelector('[data-testid=task-status]')?.textContent || '';
                  return s.includes('已完成') || s.includes('失败') || s.includes('已中断');
                }""",
                timeout=300_000,
            )
            status = page.locator("[data-testid=task-status]").inner_text()
            activity = page.locator("[data-testid=activity]").inner_text()
            diff = page.locator("[data-testid=diff-view]").inner_text()
            terminal = page.locator("[data-testid=terminal]").inner_text()
            tests = page.locator("[data-testid=test-result]").inner_text()
            stats = page.locator("[data-testid=runtime-stats]").inner_text()
            role = page.locator("[data-testid=task-role]").inner_text()
            checks["create_and_finish"] = "已完成" in status
            checks["plan_or_activity"] = "planner" in activity.lower() or "Tool:" in activity
            checks["roles"] = all(x in activity.lower() for x in ["planner", "coding", "execution", "reviewer"])
            checks["tool_trace"] = "Tool:" in activity
            checks["terminal"] = "exit=" in terminal or "passed" in terminal.lower()
            checks["test_result"] = "passed" in tests.lower()
            checks["diff_plus_minus"] = "+" in diff and "-" in diff
            checks["changed_files"] = "calc.py" in page.content()
            checks["tokens_iteration"] = "Tokens:" in stats and "Iteration:" in stats
            checks["final_role"] = bool(role.strip())
            notes.append(f"coding_status={status}")
            notes.append(f"roles_ok={checks['roles']}")

            page2 = browser.new_page()
            page2.goto(WEB, wait_until="networkidle")
            _fill_and_create(
                page2,
                stop_repo,
                "Read the repository slowly and plan a careful fix of add(). Take your time.",
            )
            page2.wait_for_function(
                """() => (document.querySelector('[data-testid=activity]')?.innerText || '').length > 0""",
                timeout=60_000,
            )
            before = (stop_repo / "calc.py").read_text(encoding="utf-8")
            mtime = (stop_repo / "calc.py").stat().st_mtime
            page2.locator("[data-testid=stop-task]").click()
            page2.wait_for_function(
                """() => {
                  const s = document.querySelector('[data-testid=task-status]')?.textContent || '';
                  return s.includes('已中断') || s.includes('已完成') || s.includes('失败');
                }""",
                timeout=60_000,
            )
            time.sleep(8)
            after_status = page2.locator("[data-testid=task-status]").inner_text()
            later_mtime = (stop_repo / "calc.py").stat().st_mtime
            later_text = (stop_repo / "calc.py").read_text(encoding="utf-8")
            checks["stop_status"] = "已中断" in after_status
            checks["stop_no_late_write"] = later_mtime == mtime or later_text == before
            if "已完成" in after_status:
                notes.append("stop_race: task finished before interrupt landed")
                checks["stop_status"] = False
            notes.append(f"stop_status={after_status}")
            browser.close()
    finally:
        shutil.rmtree(coding_repo.parent, ignore_errors=True)
        shutil.rmtree(stop_repo.parent, ignore_errors=True)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "web_browser_e2e",
        "base_url": WEB,
        "checks": checks,
        "notes": notes,
        "passed": all(checks.values()),
    }
    json_path = out_dir / "web-e2e-report.json"
    md_path = out_dir / "web-e2e-report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Web browser E2E", "", f"passed: {payload['passed']}", ""]
    for key, value in checks.items():
        lines.append(f"- [{'x' if value else ' '}] {key}")
    lines.extend(["", "## Notes", ""] + [f"- {n}" for n in notes])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "checks": checks, "notes": notes}, ensure_ascii=False))
    if not payload["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
