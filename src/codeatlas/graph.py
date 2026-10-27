"""Graph model for codeatlas: nodes, edges, queries, and Mermaid output."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


class Atlas:
    """An in-memory knowledge graph of a Python codebase."""

    def __init__(self, nodes=None, edges=None, stats=None):
        self.nodes = list(nodes or [])
        self.edges = list(edges or [])
        self._stats = dict(stats or {})
        self._by_id = {n["id"]: n for n in self.nodes}

    # -- construction helpers ------------------------------------------------
    def node_by_id(self, node_id: str):
        return self._by_id.get(node_id)

    def resolve(self, symbol: str):
        """Resolve a user-supplied symbol to a node.

        Exact id match wins; otherwise a unique suffix / simple-name match.
        Returns the node dict or None. Ambiguous matches return the first
        candidate whose id ends with the symbol, sorted by id.
        """
        if symbol in self._by_id:
            return self._by_id[symbol]
        suffix = [n for n in self.nodes if n["id"].endswith("." + symbol)]
        if suffix:
            return sorted(suffix, key=lambda n: n["id"])[0]
        simple = [n for n in self.nodes if n["id"].rsplit(".", 1)[-1] == symbol]
        if simple:
            return sorted(simple, key=lambda n: n["id"])[0]
        return None

    # -- serialisation -------------------------------------------------------
    def stats(self) -> dict:
        if self._stats:
            return dict(self._stats)
        return compute_stats(self.nodes, self.edges, files=0)

    def to_dict(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges, "stats": self.stats()}

    def save(self, path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path) -> "Atlas":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            nodes=data.get("nodes", []),
            edges=data.get("edges", []),
            stats=data.get("stats", {}),
        )

    # -- queries ---------------------------------------------------------------
    def search(self, term: str):
        """Case-insensitive substring search over ids and docstrings."""
        needle = term.lower()
        return [
            n
            for n in self.nodes
            if needle in n["id"].lower()
            or needle in (n.get("docstring_first_line") or "").lower()
        ]

    def _related(self, node_id: str, kind: str, direction: str):
        out = []
        for e in self.edges:
            if e["kind"] != kind:
                continue
            if direction == "out" and e["src"] == node_id:
                out.append(e["dst"])
            elif direction == "in" and e["dst"] == node_id:
                out.append(e["src"])
        return sorted(set(out))

    def callers_of(self, symbol: str):
        node = self.resolve(symbol)
        if node is None:
            return []
        return self._related(node["id"], "calls", "in")

    def callees_of(self, symbol: str):
        node = self.resolve(symbol)
        if node is None:
            return []
        return self._related(node["id"], "calls", "out")

    def imports_of(self, symbol: str):
        node = self.resolve(symbol)
        if node is None:
            return []
        return self._related(node["id"], "imports", "out")

    def imported_by(self, symbol: str):
        node = self.resolve(symbol)
        if node is None:
            return []
        return self._related(node["id"], "imports", "in")

    def module_deps(self, symbol: str) -> dict:
        node = self.resolve(symbol)
        if node is None:
            return {"module": symbol, "imports": [], "imported_by": []}
        return {
            "module": node["id"],
            "imports": self.imports_of(node["id"]),
            "imported_by": self.imported_by(node["id"]),
        }

    # -- Mermaid ---------------------------------------------------------------
    def to_mermaid(self) -> str:
        """A Mermaid flowchart of module-level imports."""
        modules = sorted(n["id"] for n in self.nodes if n["kind"] == "module")
        alias = {mid: f"m{i}" for i, mid in enumerate(modules)}
        lines = ["flowchart TD"]
        for mid in modules:
            lines.append(f'    {alias[mid]}["{mid}"]')
        seen = set()
        for e in self.edges:
            if e["kind"] != "imports":
                continue
            if e["src"] in alias and e["dst"] in alias and e["src"] != e["dst"]:
                key = (e["src"], e["dst"])
                if key not in seen:
                    seen.add(key)
                    lines.append(f"    {alias[e['src']]} --> {alias[e['dst']]}")
        return "\n".join(lines) + "\n"


def compute_stats(nodes, edges, files: int = 0) -> dict:
    edge_kinds = Counter(e["kind"] for e in edges)
    node_kinds = Counter(n["kind"] for n in nodes)
    return {
        "files": files,
        "nodes": len(nodes),
        "edges": len(edges),
        "nodes_by_kind": dict(sorted(node_kinds.items())),
        "edges_by_kind": dict(sorted(edge_kinds.items())),
    }
