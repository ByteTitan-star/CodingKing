import json
import os
import sys


def main() -> int:
    raw = os.environ.get("CODERKING_TOOL_ARGS", "{}")
    args = json.loads(raw)
    url = str(args.get("url") or "")
    print(f"browser_smoke ok url={url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
