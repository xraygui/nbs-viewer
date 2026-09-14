"""
The two hard rules for ``models/plot``: no runtime cycle, no import dodges.

These are hazards rather than preferences, which is why they are a test and
the working-set table is not. A runtime import cycle among siblings is a
latent ``ImportError`` that depends on which module a caller happens to
reach first, and a sibling import hidden in a function body is how a cycle
gets past the interpreter without being removed from the design -- the
second rule exists so the first cannot be satisfied by concealment.

Nothing here caps a working set. A threshold would turn a diagnostic into a
target, and the count is trivially gamed by collecting free functions into a
class that is only a namespace. Print the table with::

    pixi run python -m tools.module_graph
"""

from __future__ import annotations

import textwrap

import pytest

from tools.module_graph import (
    find_cycles,
    function_local_imports,
    read_package,
    runtime_edges,
)

PACKAGE = "nbs_viewer/models/plot"

#: Function-local sibling imports allowed to remain, as
#: ``(module, enclosing function, imported sibling)``.
#:
#: Empty, and meant to stay that way. It held three entries when this file
#: was written, all of them reaching into ``region_mesh`` for cell geometry
#: and together making up the whole ``plot_view_frame`` <-> ``region_mesh``
#: runtime cycle; moving that geometry onto the frame removed all three at
#: once. Adding an entry back is a decision to keep a cycle, not a way to
#: get a red suite green.
KNOWN_FUNCTION_LOCAL_IMPORTS = frozenset()


@pytest.fixture(scope="module")
def facts():
    """
    Parse the package once for every rule in this file.
    """
    return read_package(PACKAGE)


def test_no_runtime_import_cycle(facts):
    """
    No two modules in the package may import each other at runtime.

    Annotation-only imports are excluded: a name used in a type hint is
    never fetched, so ``if TYPE_CHECKING`` pairs such as a controller naming
    the session that owns it are expected and harmless. The known
    function-local imports are excluded too, because the rule below already
    reports them and the same defect should not be named twice.
    """
    graph = runtime_edges(facts, KNOWN_FUNCTION_LOCAL_IMPORTS)
    cycles = find_cycles(graph)
    assert cycles == [], "runtime import cycles: " + "; ".join(
        " -> ".join(cycle + [cycle[0]]) for cycle in cycles
    )


def test_function_local_sibling_imports_are_exactly_the_known_ones(facts):
    """
    A sibling import inside a function body must be on the allowlist.

    Equality rather than containment. A new dodge fails because it is not
    listed, and a listed one that has been fixed fails because the allowlist
    still claims it -- which is what makes the list shrink to nothing instead
    of quietly outliving the problem.
    """
    found = {
        (imp.module, imp.function, imp.target)
        for imp in function_local_imports(facts)
    }
    assert found == set(KNOWN_FUNCTION_LOCAL_IMPORTS), (
        f"new dodges: {sorted(found - set(KNOWN_FUNCTION_LOCAL_IMPORTS))}; "
        f"stale allowlist entries: "
        f"{sorted(set(KNOWN_FUNCTION_LOCAL_IMPORTS) - found)}"
    )


def test_a_non_sibling_import_in_a_function_is_not_a_dodge(facts):
    """
    The rule is about siblings, not about every deferred import.

    ``region_mesh.mask_from_vertices`` imports ``matplotlib.path`` in its
    body to keep a heavy optional dependency off the module's import path.
    That is a cost decision about a third-party package, not a cycle being
    concealed, so it must not be reported.
    """
    source = facts["region_mesh"].path.read_text()
    assert "    from matplotlib.path import Path" in source, (
        "this test is only meaningful while region_mesh still defers a "
        "third-party import into a function body"
    )
    bodies = [
        imp
        for imp in function_local_imports(facts)
        if imp.module == "region_mesh"
    ]
    assert bodies == []


# ---------------------------------------------------------------------------
# The detector itself, on a package small enough to read
# ---------------------------------------------------------------------------


def _write_package(root, files):
    """
    Write a throwaway package and return its directory.
    """
    package = root / "sample_pkg"
    package.mkdir()
    for name, source in files.items():
        (package / name).write_text(textwrap.dedent(source))
    return package


def test_a_module_level_pair_is_a_cycle(tmp_path):
    """
    Two modules importing each other at the top level is caught.
    """
    package = _write_package(
        tmp_path,
        {
            "left.py": "from .right import go\n",
            "right.py": "from .left import back\n",
        },
    )
    facts = read_package(package)
    assert find_cycles(runtime_edges(facts)) == [["left", "right"]]


def test_an_annotation_only_pair_is_not_a_cycle(tmp_path):
    """
    A ``TYPE_CHECKING`` import does not close a cycle.
    """
    package = _write_package(
        tmp_path,
        {
            "left.py": "from .right import go\n",
            "right.py": """
                from typing import TYPE_CHECKING

                if TYPE_CHECKING:
                    from .left import Back
                """,
        },
    )
    facts = read_package(package)
    assert find_cycles(runtime_edges(facts)) == []


def test_a_function_local_import_still_closes_a_cycle(tmp_path):
    """
    Deferring an import to call time hides a cycle; it does not remove it.
    """
    package = _write_package(
        tmp_path,
        {
            "left.py": "from .right import go\n",
            "right.py": """
                def back():
                    from .left import go

                    return go
                """,
        },
    )
    facts = read_package(package)
    assert find_cycles(runtime_edges(facts)) == [["left", "right"]]
    assert [
        (imp.module, imp.function, imp.target)
        for imp in function_local_imports(facts)
    ] == [("right", "back", "left")]


def test_a_method_local_import_reports_its_class_and_method(tmp_path):
    """
    An import buried in a method names the path to it, not just the file.
    """
    package = _write_package(
        tmp_path,
        {
            "left.py": "VALUE = 1\n",
            "right.py": """
                class Holder:
                    def fetch(self):
                        from .left import VALUE

                        return VALUE
                """,
        },
    )
    facts = read_package(package)
    (only,) = function_local_imports(facts)
    assert (only.module, only.function, only.target) == (
        "right",
        "fetch",
        "left",
    )


def test_an_absolute_self_import_counts_as_a_sibling(tmp_path):
    """
    Spelling a sibling absolutely does not exempt it from the rules.
    """
    package = _write_package(
        tmp_path,
        {
            "left.py": "from sample_pkg.right import go\n",
            "right.py": "from sample_pkg.left import back\n",
        },
    )
    facts = read_package(package)
    assert find_cycles(runtime_edges(facts)) == [["left", "right"]]
