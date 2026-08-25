# CoderKing eval report (`bug_fix-live`)

Generated: 2026-08-25T05:56:57.867481+00:00

## Summary

- task_success_rate: 1.0
- test_pass_rate: 1.0
- repair_success_rate: 0.0
- avg_iterations: 6.0
- avg_tool_calls: 7.0
- token_usage: 4970.0

## Extra

- llm: live openai-compatible
- model: glm-5.2
- endpoint_host: open.bigmodel.cn/api/coding/paas/v4
- sandbox_mode: local
- scripted: False

## Tasks

### bug_fix_add (bug_fix)

- success: True
- test_pass: True
- iterations: 6
- tool_calls: 7
- repair_count: 0
- model: glm-5.2
- changed_files: calc.py
- tokens: 4562 / 408

```diff
--- calc.py
+++ calc.py
@@ -1,2 +1,2 @@
 def add(a: int, b: int) -> int:
-    return a - b
+    return a + b

```
