"""Command-line interface for codeatlas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .graph import Atlas
from .scanner import scan_path


def _print_stats(atlas: Atlas) -> None:
    s = atlas.stats()
    print(f"files: {s.get('files', 0)}")
    print(f"nodes: {s.get('nodes', len(atlas.nodes))}")
    print(f"edges: {s.get('edges', len(atlas.edges))}")
    by_kind = s.get("nodes_by_kind", {})
    if by_kind:
        print("nodes by kind: " + ", ".join(f"{k}={v}" for k, v in by_kind.items()))
    e_by_kind = s.get("edges_by_kind", {})
    if e_by_kind:
        print("edges by kind: " + ", ".join(f"{k}={v}" for k, v in e_by_kind.items()))


def _cmd_build(args) -> int:
    atlas = scan_path(args.path)
    out = args.output or "atlas.json"
    atlas.save(out)
    print(f"wrote {out}")
    _print_stats(atlas)
    return 0


def _cmd_stats(args) -> int:
    _print_stats(Atlas.load(args.atlas))
    return 0


def _cmd_search(args) -> int:
    atlas = Atlas.load(args.atlas)
    results = atlas.search(args.term)
    if not results:
        print(f"no symbols matching {args.term!r}")
        return 0
    for n in results:
        doc = f" — {n['docstring_first_line']}" if n.get("docstring_first_line") else ""
        print(f"{n['id']} [{n['kind']}] ({n['file']}:{n['line']}){doc}")
    return 0


def _cmd_query(args) -> int:
    atlas = Atlas.load(args.atlas)
    node = atlas.resolve(args.symbol)
    if node is None:
        print(f"symbol not found: {args.symbol}")
        return 1
    nid = node["id"]
    if args.callers:
        title, items = "callers", atlas.callers_of(nid)
    elif args.callees:
        title, items = "callees", atlas.callees_of(nid)
    elif args.imports:
        title, items = "imports", atlas.imports_of(nid)
    else:
        doc = node.get("docstring_first_line") or ""
        print(f"{nid} [{node['kind']}] ({node['file']}:{node['line']})")
        if doc:
            print(f"  {doc}")
        for label, values in (
            ("callers", atlas.callers_of(nid)),
            ("callees", atlas.callees_of(nid)),
            ("imports", atlas.imports_of(nid)),
            ("imported_by", atlas.imported_by(nid)),
        ):
            if values:
                print(f"  {label}:")
                for v in values:
                    print(f"    - {v}")
        return 0
    print(f"{title} of {nid}:")
    if not items:
        print("  (none)")
    for item in items:
        print(f"  - {item}")
    return 0


def _cmd_map(args) -> int:
    atlas = Atlas.load(args.atlas)
    mermaid = atlas.to_mermaid()
    if args.out:
        Path(args.out).write_text(mermaid, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(mermaid, end="")
    return 0


def _cmd_mcp(args) -> int:
    from .mcp_server import serve

    atlas = Atlas.load(args.atlas)
    serve(atlas)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeatlas",
        description="Turn a Python codebase into a queryable knowledge graph.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="scan a codebase and write atlas.json")
    p.add_argument("path")
    p.add_argument("-o", "--output", default=None)
    p.set_defaults(func=_cmd_build)

    p = sub.add_parser("query", help="show a symbol and its relationships")
    p.add_argument("atlas")
    p.add_argument("symbol")
    p.add_argument("--callers", action="store_true")
    p.add_argument("--callees", action="store_true")
    p.add_argument("--imports", action="store_true")
    p.set_defaults(func=_cmd_query)

    p = sub.add_parser("search", help="search symbols by substring")
    p.add_argument("atlas")
    p.add_argument("term")
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser("map", help="emit a Mermaid flowchart of module imports")
    p.add_argument("atlas")
    p.add_argument("--out", default=None)
    p.set_defaults(func=_cmd_map)

    p = sub.add_parser("stats", help="print build statistics for an atlas")
    p.add_argument("atlas")
    p.set_defaults(func=_cmd_stats)

    p = sub.add_parser("mcp", help="serve the atlas over stdio as an MCP server")
    p.add_argument("atlas")
    p.set_defaults(func=_cmd_mcp)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
