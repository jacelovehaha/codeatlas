"""Scanner: walk .py files, parse them with ``ast``, build an Atlas.

Resolution heuristics (also documented in the README):

* imports -- an import is linked to a project module when its dotted path
  matches a scanned module exactly, or resolves relative to the importing
  package. External imports (stdlib / third-party) produce no edge.
* inherits -- a base class is linked when a class with the same simple name
  (or matching dotted suffix) exists in the project; a class defined in the
  same module wins over one elsewhere.
* calls -- a call is linked when the called name matches a project function
  or method. ``self.x()`` prefers a sibling method of the same class, a bare
  ``name()`` prefers a function in the same module, and otherwise the unique
  (or first, sorted) global match wins. This is name-based static analysis:
  it can miss dynamic dispatch and can occasionally link a coincidental
  same-named function. Treat call edges as a good map, not ground truth.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .graph import Atlas, compute_stats

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", ".tox", "node_modules"}


def _first_line(text):
    if not text:
        return ""
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def _dotted(node):
    """Best-effort dotted name for an expression (Name/Attribute chains)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return parts[-1] if parts else ""


class _ModuleScan:
    def __init__(self, module_id, rel_file, is_package):
        self.module_id = module_id
        self.file = rel_file
        self.is_package = is_package
        self.nodes = []
        self.raw_imports = []  # candidate dotted names, most specific first
        self.raw_inherits = []  # (class_id, base_dotted)
        self.raw_calls = []  # (caller_id, called_dotted, via_self_class_or_None)


def _module_id_for(root: Path, file_path: Path) -> tuple[str, bool]:
    rel = file_path.relative_to(root)
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__.py"
    if is_package:
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts), is_package


def _package_of(scan: _ModuleScan) -> str:
    if scan.is_package:
        return scan.module_id
    return scan.module_id.rpartition(".")[0]


def _collect(tree: ast.Module, scan: _ModuleScan) -> None:
    scan.nodes.append(
        {
            "id": scan.module_id,
            "kind": "module",
            "file": scan.file,
            "line": 1,
            "docstring_first_line": _first_line(ast.get_docstring(tree)),
        }
    )
    for node in tree.body:
        _collect_node(node, scan, prefix=scan.module_id, klass=None)


def _collect_node(node, scan: _ModuleScan, prefix: str, klass: str | None) -> None:
    if isinstance(node, ast.ClassDef):
        cid = f"{prefix}.{node.name}"
        scan.nodes.append(
            {
                "id": cid,
                "kind": "class",
                "file": scan.file,
                "line": node.lineno,
                "docstring_first_line": _first_line(ast.get_docstring(node)),
            }
        )
        for base in node.bases:
            dotted = _dotted(base)
            if dotted:
                scan.raw_inherits.append((cid, dotted))
        for child in node.body:
            _collect_node(child, scan, prefix=cid, klass=cid)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fid = f"{prefix}.{node.name}"
        scan.nodes.append(
            {
                "id": fid,
                "kind": "function",
                "file": scan.file,
                "line": node.lineno,
                "docstring_first_line": _first_line(ast.get_docstring(node)),
            }
        )
        _collect_calls(node, scan, caller=fid, klass=klass)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                _collect_node(child, scan, prefix=fid, klass=klass)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        _collect_import(node, scan)
    else:
        # Imports can hide inside if/try blocks at module level.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                _collect_import(child, scan)


def _collect_import(node, scan: _ModuleScan) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            scan.raw_imports.append([alias.name])
    else:  # ImportFrom
        if node.level:
            pkg_parts = _package_of(scan).split(".") if _package_of(scan) else []
            # level 1 = current package, level 2 = its parent, ...
            keep = len(pkg_parts) - (node.level - 1)
            base_parts = pkg_parts[:keep] if keep > 0 else []
            base = ".".join(base_parts)
            mod = f"{base}.{node.module}" if node.module and base else (node.module or base)
        else:
            mod = node.module or ""
        candidates = []
        for alias in node.names:
            if mod:
                candidates.append(f"{mod}.{alias.name}")
            candidates.append(alias.name)
        if mod:
            candidates.append(mod)
        if candidates:
            scan.raw_imports.append(candidates)


def _collect_calls(func_node, scan: _ModuleScan, caller: str, klass: str | None) -> None:
    """Record calls made directly by *func_node* (not by nested defs)."""

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # nested defs get their own caller entry
            if isinstance(child, ast.Call):
                dotted = _dotted(child.func)
                if dotted:
                    via_self = None
                    if (
                        isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id in ("self", "cls")
                    ):
                        via_self = klass
                    scan.raw_calls.append((caller, dotted, via_self))
            visit(child)

    visit(func_node)


def scan_path(root) -> Atlas:
    """Scan the directory (or single file) at *root* and return an Atlas."""
    root = Path(root)
    if root.is_file():
        files = [root]
        base = root.parent
    else:
        base = root
        files = []
        for path in sorted(root.rglob("*.py")):
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            files.append(path)

    scans: list[_ModuleScan] = []
    for path in files:
        module_id, is_package = _module_id_for(base, path)
        if not module_id:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        scan = _ModuleScan(module_id, path.relative_to(base).as_posix(), is_package)
        _collect(tree, scan)
        scans.append(scan)

    nodes = [n for s in scans for n in s.nodes]
    module_ids = {s.module_id for s in scans}
    class_nodes = [n for n in nodes if n["kind"] == "class"]
    func_nodes = [n for n in nodes if n["kind"] == "function"]
    edges: set[tuple[str, str, str]] = set()

    def add(src, dst, kind):
        if src and dst:
            edges.add((src, dst, kind))

    # imports
    for s in scans:
        for candidates in s.raw_imports:
            for cand in candidates:
                if cand in module_ids and cand != s.module_id:
                    add(s.module_id, cand, "imports")
                    break

    # inherits
    for s in scans:
        for class_id, base_dotted in s.raw_inherits:
            simple = base_dotted.rsplit(".", 1)[-1]
            matches = [
                n
                for n in class_nodes
                if n["id"] != class_id
                and (n["id"] == base_dotted or n["id"].endswith("." + base_dotted)
                     or n["id"].rsplit(".", 1)[-1] == simple)
            ]
            if not matches:
                continue
            same_module = [n for n in matches if n["file"] == s.file]
            chosen = sorted(same_module or matches, key=lambda n: n["id"])[0]
            add(class_id, chosen["id"], "inherits")

    # calls
    for s in scans:
        for caller, dotted, via_self in s.raw_calls:
            simple = dotted.rsplit(".", 1)[-1]
            matches = [
                n for n in func_nodes if n["id"].rsplit(".", 1)[-1] == simple
            ]
            if not matches:
                continue
            chosen = None
            if via_self:
                siblings = [n for n in matches if n["id"].startswith(via_self + ".")]
                if siblings:
                    chosen = siblings[0]
            if chosen is None:
                same_module = [n for n in matches if n["file"] == s.file]
                pool = same_module or matches
                chosen = sorted(pool, key=lambda n: n["id"])[0]
            add(caller, chosen["id"], "calls")

    edge_list = [
        {"src": src, "dst": dst, "kind": kind}
        for src, dst, kind in sorted(edges)
    ]
    stats = compute_stats(nodes, edge_list, files=len(files))
    return Atlas(nodes=nodes, edges=edge_list, stats=stats)
