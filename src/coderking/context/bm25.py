from __future__ import annotations

from collections import Counter
from math import log
from pathlib import Path

from coderking.workspace import iter_files


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch in "._":
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


class BM25Index:
    def __init__(self, workspace: Path, *, k1: float = 1.5, b: float = 0.75):
        self.workspace = workspace.resolve()
        self.k1 = k1
        self.b = b
        self.docs: list[tuple[str, list[str]]] = []
        for path in iter_files(workspace, max_files=250):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(self.workspace).as_posix()
            self.docs.append((rel, tokenize(text[:40_000])))
        self.avgdl = sum(len(tokens) for _, tokens in self.docs) / max(len(self.docs), 1)
        self.df: Counter[str] = Counter()
        for _, tokens in self.docs:
            self.df.update(set(tokens))

    def search(self, query: str, *, k: int = 8) -> list[tuple[str, float]]:
        q_tokens = tokenize(query)
        scored: list[tuple[str, float]] = []
        n = max(len(self.docs), 1)
        for rel, tokens in self.docs:
            tf = Counter(tokens)
            dl = max(len(tokens), 1)
            score = 0.0
            for term in q_tokens:
                if term not in tf:
                    continue
                idf = log((n - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1))
                score += idf * (freq * (self.k1 + 1)) / denom
            if score:
                scored.append((rel, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]
