# CoderKing eval report (`latest`)

Generated: 2026-08-28T05:46:21.803137+00:00

## Summary

- task_success_rate: 1.0
- test_pass_rate: 1.0
- repair_success_rate: 0.0
- avg_iterations: 5.0
- avg_tool_calls: 5.0
- token_usage: 0.0

## Extra

- llm: scripted fixture (no live API key in this environment)
- docker_unit: see tests/test_docker.py

## Tasks

### bug_fix_add (bug_fix)

- success: True
- test_pass: True
- iterations: 5
- tool_calls: 5
- repair_count: 0
- model: gpt-4o-mini
- changed_files: calc.py
- tokens: 0 / 0

```diff
--- calc.py
+++ calc.py
@@ -1,2 +1,2 @@
-def add(a: int, b: int) -> int:
-    return a - b
+def add(a, b):
+    return a + b

```

### feature_add_greet (feature_add)

- success: True
- test_pass: True
- iterations: 5
- tool_calls: 5
- repair_count: 0
- model: gpt-4o-mini
- changed_files: greet.py
- tokens: 0 / 0

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
- iterations: 5
- tool_calls: 5
- repair_count: 0
- model: gpt-4o-mini
- changed_files: geometry.py
- tokens: 0 / 0

```diff
--- geometry.py
+++ geometry.py
@@ -1,6 +1,8 @@
-def box_area(w: int, h: int) -> int:
+def rect_area(w: int, h: int) -> int:
     return w * h
 
+def box_area(w: int, h: int) -> int:
+    return rect_area(w, h)
 
 def square_area(side: int) -> int:
-    return side * side
+    return rect_area(side, side)

```
