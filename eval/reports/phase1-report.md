# CoderKing eval report (`phase1-report`)

Generated: 2026-08-29T14:58:19.513716+00:00

## Summary

- task_success_rate: 1.0
- test_pass_rate: 1.0
- repair_success_rate: 0.0
- avg_iterations: 7.333333333333333
- avg_tool_calls: 8.0
- token_usage: 24526.0

## Extra

- llm: {'mode': 'live', 'model': 'glm-5.2', 'base_url': 'https://open.bigmodel.cn/api/coding/paas/v4'}
- sandbox_mode: local

## Tasks

### bug_fix_add (bug_fix)

- success: True
- test_pass: True
- iterations: 5
- tool_calls: 6
- repair_count: 0
- model: glm-5.2
- changed_files: calc.py
- tokens: 3791 / 329

```diff
--- calc.py
+++ calc.py
@@ -1,2 +1,2 @@
 def add(a: int, b: int) -> int:
-    return a - b
+    return a + b

```

### feature_add_greet (feature_add)

- success: True
- test_pass: True
- iterations: 9
- tool_calls: 9
- repair_count: 0
- model: glm-5.2
- changed_files: (none)
- tokens: 11201 / 611

```diff
--- greet.py
+++ greet.py
@@ -1,2 +1,2 @@
 def greet(name: str) -> str:
-    raise NotImplementedError
+    return f"hello, {name}"

```

### refactor_area (refactor)

- success: True
- test_pass: True
- iterations: 8
- tool_calls: 9
- repair_count: 0
- model: glm-5.2
- changed_files: geometry.py
- tokens: 8042 / 552

```diff
--- geometry.py
+++ geometry.py
@@ -1,6 +1,10 @@
-def box_area(w: int, h: int) -> int:
+def rect_area(w: int, h: int) -> int:
     return w * h
 
 
+def box_area(w: int, h: int) -> int:
+    return rect_area(w, h)
+
+
 def square_area(side: int) -> int:
-    return side * side
+    return rect_area(side, side)

```
