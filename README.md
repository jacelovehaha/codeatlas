# codeatlas

Turn a Python codebase into a queryable knowledge graph — for AI agents and
for humans. Point `codeatlas` at a directory of `.py` files and it builds an
**atlas**: every module, class, and function as a node, and the imports,
inheritance, and calls between them as edges. Query the atlas from the
command line, render the module map as a Mermaid diagram, or serve it to an
LLM agent over MCP so the agent can answer "who calls this?" without reading
the whole repository.

Zero third-party dependencies. Python ≥ 3.10. The only parser is the standard
library's `ast` module — your code is analysed, never executed.

## Quickstart

```bash
pip install .

codeatlas build path/to/project -o atlas.json
codeatlas stats atlas.json
codeatlas search atlas.json login
codeatlas query atlas.json myapp.auth.login --callers
codeatlas map atlas.json --out graph.mmd
codeatlas mcp atlas.json        # serve the atlas to an agent over stdio
```

No-install use from a checkout:

```bash
PYTHONPATH=src python -m codeatlas build path/to/project
```

## What goes into the atlas

`atlas.json` is plain JSON, easy to diff, grep, or feed to other tools:

```json
{
  "nodes": [
    {"id": "shop.orders.DiscountedOrder", "kind": "class",
     "file": "shop/orders.py", "line": 14,
     "docstring_first_line": "An order with a loyal-customer discount."}
  ],
  "edges": [
    {"src": "shop.orders", "dst": "shop.pricing", "kind": "imports"}
  ],
  "stats": {"files": 3, "nodes": 9, "edges": 5,
            "nodes_by_kind": {"class": 2, "function": 4, "module": 3},
            "edges_by_kind": {"calls": 3, "imports": 1, "inherits": 1}}
}
```

Node ids are dotted paths: `package.module.Class.method`. Node kinds are
`module`, `class`, and `function` (methods are functions under their class).
Edge kinds are `imports`, `inherits`, and `calls`.

## Commands

| Command | What it does |
|---|---|
| `codeatlas build <path> [-o atlas.json]` | Scan a directory (or single file) and write the atlas |
| `codeatlas query <atlas> <symbol> [--callers\|--callees\|--imports]` | Show a symbol, or one relationship as a list |
| `codeatlas search <atlas> <term>` | Substring search over symbol ids and docstrings |
| `codeatlas map <atlas> [--out graph.mmd]` | Mermaid flowchart of module-level imports |
| `codeatlas stats <atlas>` | Files / nodes / edges, broken down by kind |
| `codeatlas mcp <atlas>` | Stdio MCP server (see below) |

Symbols in `query` do not need to be full ids: an exact id wins, then a
unique dotted suffix, then a simple name.

## MCP server mode

`codeatlas mcp atlas.json` runs a small stdio JSON-RPC MCP server
(`initialize`, `tools/list`, `tools/call`) with four tools:

- `search_symbols` — find symbols by substring
- `callers_of` — who calls a symbol
- `callees_of` — what a symbol calls
- `module_deps` — what a module imports, and what imports it

Wire it into any MCP-speaking agent and the agent can navigate the codebase
structurally — impact analysis before an edit, orientation in an unfamiliar
repository — instead of guessing from filenames.

## How resolution works (honestly)

Static, name-based analysis has limits. codeatlas uses these heuristics:

- **Imports** are linked only when the dotted path matches a scanned project
  module (relative imports are resolved against the importing package).
  Standard-library and third-party imports produce no edge. Imports are
  collected at module level, including inside top-level `if`/`try` blocks.
- **Inheritance** links a base class when a class with the same simple name
  (or a matching dotted suffix) exists in the project; a class from the same
  module wins.
- **Calls** link when the called name matches a project function or method:
  `self.x()` prefers a sibling method of the same class, a bare `name()`
  prefers a function in the same module, and otherwise the first matching
  name in the project wins.

That means dynamic dispatch, `getattr`, decorators that replace functions,
and coincidental same-named helpers can produce missing or wrong call edges.
Treat the atlas as a good map of the territory — not the territory.

## Self-scan

codeatlas, scanned with itself (`codeatlas build src`):

- **6 files, 51 nodes** (6 modules, 2 classes, 43 functions),
  **64 edges** (58 calls, 6 imports).

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

24 tests cover the scanner (a fixture package with known imports,
inheritance, and calls), the query layer, the CLI, Mermaid output, and an
MCP round-trip driven through a subprocess.

## What is included

- `src/codeatlas/scanner.py` — directory walking and `ast` extraction
- `src/codeatlas/graph.py` — the `Atlas` model, queries, stats, Mermaid
- `src/codeatlas/cli.py` — the six subcommands
- `src/codeatlas/mcp_server.py` — the stdio MCP server
- `examples/demo_package/` — a three-module package to try it on

## Roadmap

- Cross-file type-aware call resolution
- HTML atlas viewer
- Incremental rebuilds

## License

MIT — see `LICENSE`.
