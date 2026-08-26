# CoderKing showcase assets

Product screenshots and media used in the root `README.md` / `README_zh.md`.

## Directory layout

```text
docs/showcase/
├── README.md                 # This file — capture & update guide
├── assets/
│   ├── product-workspace.png # Three-column Web workspace (Chat / Code / Runtime)
│   └── product-diff.png      # Diff viewer close-up after a repair pass
└── demo.html                 # Static UI mock for reproducible screenshots (optional)
```

## Recommended specs

| Asset | Size | Notes |
| --- | --- | --- |
| `product-workspace.png` | 1920×1080 or 16:9 | Full Engineering Workspace with plan, file tree, terminal |
| `product-diff.png` | 1920×1080 or 16:9 | Unified diff with `+` / `-` lines visible |

Keep PNG under ~500 KB when possible (GitHub renders large images but repo size matters).

## Capture from a running stack

1. Start API: `coderking serve --port 8000`
2. Start Web: `cd web && npm run dev` (or `npm run build` + serve `web/dist`)
3. Run a short scripted task (e.g. bug_fix eval repo) until tests pass and diff is visible.
4. Screenshot the browser at 100% zoom, crop to UI chrome if needed.
5. Save over `docs/showcase/assets/*.png` and commit.

### Automated capture (Playwright)

```bash
pip install playwright
playwright install chromium
python scripts/capture_showcase.py
```

The script opens `docs/showcase/demo.html` locally and writes PNGs into `docs/showcase/assets/`. Replace with live-app captures when you have a stable demo task.

## Updating README

After replacing images, verify links in:

- `README.md` — **Product showcase** and **Product interface** sections
- `README_zh.md` — **产品展示** and **产品界面** sections

Use relative paths from repo root, e.g. `docs/showcase/assets/product-workspace.png`.
