import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codeatlas.cli import main
from codeatlas.graph import Atlas
from codeatlas.mcp_server import handle_message
from codeatlas.scanner import scan_path

CORE = '''"""Core module."""

import pkg.util
from pkg.util import add


class Animal:
    """An animal."""

    def speak(self):
        """Make a sound."""
        return "..."


class Dog(Animal):
    """A dog."""

    def speak(self):
        """Bark."""
        return "woof"

    def fetch(self):
        """Fetch, barking and adding."""
        self.speak()
        return add(1, 2)


def run():
    """Run the demo."""
    d = Dog()
    return d.fetch()
'''

UTIL = '''"""Utility module."""


def add(a, b):
    """Add two numbers."""
    return a + b


def compute():
    """Compute a sum."""
    return add(2, 3)
'''


def write_fixture(root: Path) -> Path:
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Fixture package."""\n', encoding="utf-8")
    (pkg / "core.py").write_text(CORE, encoding="utf-8")
    (pkg / "util.py").write_text(UTIL, encoding="utf-8")
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "junk.py").write_text("def junk():\n    pass\n", encoding="utf-8")
    return root


class FixtureTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = write_fixture(Path(self._tmp.name))
        self.atlas = scan_path(self.root)
        self.ids = {n["id"] for n in self.atlas.nodes}
        self.edge_set = {(e["src"], e["dst"], e["kind"]) for e in self.atlas.edges}

    def tearDown(self):
        self._tmp.cleanup()


class TestScanner(FixtureTestCase):
    def test_module_nodes(self):
        for mid in ("pkg", "pkg.core", "pkg.util"):
            self.assertIn(mid, self.ids)
            node = self.atlas.node_by_id(mid)
            self.assertEqual(node["kind"], "module")

    def test_class_and_function_ids(self):
        self.assertIn("pkg.core.Animal", self.ids)
        self.assertIn("pkg.core.Dog", self.ids)
        self.assertIn("pkg.core.Animal.speak", self.ids)
        self.assertIn("pkg.core.Dog.fetch", self.ids)
        self.assertIn("pkg.util.add", self.ids)
        self.assertEqual(self.atlas.node_by_id("pkg.core.Dog")["kind"], "class")
        self.assertEqual(self.atlas.node_by_id("pkg.util.add")["kind"], "function")

    def test_docstring_first_line(self):
        self.assertEqual(
            self.atlas.node_by_id("pkg.core")["docstring_first_line"], "Core module."
        )
        self.assertEqual(
            self.atlas.node_by_id("pkg.util.add")["docstring_first_line"],
            "Add two numbers.",
        )

    def test_pycache_skipped(self):
        self.assertNotIn("pkg.__pycache__.junk", self.ids)
        self.assertFalse(any("junk" in i for i in self.ids))

    def test_imports_edge(self):
        self.assertIn(("pkg.core", "pkg.util", "imports"), self.edge_set)

    def test_no_external_import_edges(self):
        # every imports edge must land on a project module
        for src, dst, kind in self.edge_set:
            if kind == "imports":
                self.assertIn(dst, self.ids)

    def test_inherits_edge(self):
        self.assertIn(("pkg.core.Dog", "pkg.core.Animal", "inherits"), self.edge_set)

    def test_calls_same_module_by_name(self):
        self.assertIn(("pkg.util.compute", "pkg.util.add", "calls"), self.edge_set)

    def test_calls_self_method(self):
        self.assertIn(("pkg.core.Dog.fetch", "pkg.core.Dog.speak", "calls"), self.edge_set)

    def test_calls_imported_function(self):
        self.assertIn(("pkg.core.Dog.fetch", "pkg.util.add", "calls"), self.edge_set)

    def test_stats(self):
        stats = self.atlas.stats()
        self.assertEqual(stats["files"], 3)
        self.assertEqual(stats["nodes"], len(self.atlas.nodes))
        self.assertEqual(stats["edges"], len(self.atlas.edges))
        self.assertGreaterEqual(stats["edges_by_kind"].get("calls", 0), 3)
        self.assertEqual(stats["edges_by_kind"].get("imports"), 1)
        self.assertEqual(stats["edges_by_kind"].get("inherits"), 1)

    def test_atlas_roundtrip(self):
        out = Path(self._tmp.name) / "atlas.json"
        self.atlas.save(out)
        loaded = Atlas.load(out)
        self.assertEqual({n["id"] for n in loaded.nodes}, self.ids)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("stats", data)


class TestQueries(FixtureTestCase):
    def test_search_by_id(self):
        hits = self.atlas.search("dog")
        self.assertTrue(any(n["id"] == "pkg.core.Dog" for n in hits))

    def test_search_by_docstring(self):
        hits = self.atlas.search("add two")
        self.assertEqual([n["id"] for n in hits], ["pkg.util.add"])

    def test_callers(self):
        self.assertIn("pkg.util.compute", self.atlas.callers_of("pkg.util.add"))
        self.assertIn("pkg.core.Dog.fetch", self.atlas.callers_of("add"))

    def test_callees(self):
        self.assertEqual(self.atlas.callees_of("pkg.util.compute"), ["pkg.util.add"])
        self.assertIn("pkg.core.Dog.speak", self.atlas.callees_of("pkg.core.Dog.fetch"))

    def test_module_deps(self):
        deps = self.atlas.module_deps("pkg.core")
        self.assertEqual(deps["imports"], ["pkg.util"])
        self.assertEqual(deps["imported_by"], [])
        self.assertEqual(self.atlas.module_deps("pkg.util")["imported_by"], ["pkg.core"])

    def test_mermaid(self):
        text = self.atlas.to_mermaid()
        self.assertTrue(text.startswith("flowchart TD"))
        self.assertIn('"pkg.core"', text)
        self.assertIn("-->", text)


class TestCli(FixtureTestCase):
    def _run_cli(self, argv):
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            code = main(argv)
        finally:
            sys.stdout = old
        return code, buf.getvalue()

    def test_cli_build_stats_search_query(self):
        out = str(Path(self._tmp.name) / "a.json")
        code, text = self._run_cli(["build", str(self.root), "-o", out])
        self.assertEqual(code, 0)
        self.assertIn("nodes:", text)
        code, text = self._run_cli(["stats", out])
        self.assertEqual(code, 0)
        self.assertIn("edges by kind:", text)
        code, text = self._run_cli(["search", out, "fetch"])
        self.assertIn("pkg.core.Dog.fetch", text)
        code, text = self._run_cli(["query", out, "pkg.util.add", "--callers"])
        self.assertIn("pkg.util.compute", text)
        code, text = self._run_cli(["query", out, "pkg.core", "--imports"])
        self.assertIn("pkg.util", text)

    def test_cli_map_out(self):
        out = str(Path(self._tmp.name) / "a.json")
        self._run_cli(["build", str(self.root), "-o", out])
        mmd = str(Path(self._tmp.name) / "g.mmd")
        code, _ = self._run_cli(["map", out, "--out", mmd])
        self.assertEqual(code, 0)
        self.assertIn("flowchart TD", Path(mmd).read_text(encoding="utf-8"))

    def test_cli_query_unknown_symbol(self):
        out = str(Path(self._tmp.name) / "a.json")
        self._run_cli(["build", str(self.root), "-o", out])
        code, text = self._run_cli(["query", out, "nope.nothing"])
        self.assertEqual(code, 1)
        self.assertIn("not found", text)


class TestMcp(FixtureTestCase):
    def test_handle_initialize_and_tools_list(self):
        resp = handle_message(
            self.atlas, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        self.assertEqual(resp["result"]["serverInfo"]["name"], "codeatlas")
        resp = handle_message(
            self.atlas, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(
            names, {"search_symbols", "callers_of", "callees_of", "module_deps"}
        )

    def test_handle_tools_call(self):
        resp = handle_message(
            self.atlas,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "callers_of", "arguments": {"symbol": "pkg.util.add"}},
            },
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertIn("pkg.util.compute", payload)

    def test_mcp_subprocess_roundtrip(self):
        out = Path(self._tmp.name) / "a.json"
        self.atlas.save(out)
        src = Path(__file__).resolve().parents[1] / "src"
        env = dict(os.environ, PYTHONPATH=str(src))
        lines = "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "module_deps",
                            "arguments": {"module": "pkg.core"},
                        },
                    }
                ),
            ]
        ) + "\n"
        proc = subprocess.run(
            [sys.executable, "-m", "codeatlas", "mcp", str(out)],
            input=lines,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        self.assertEqual([r["id"] for r in responses], [1, 2, 3])
        deps = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertEqual(deps["imports"], ["pkg.util"])


if __name__ == "__main__":
    unittest.main()
