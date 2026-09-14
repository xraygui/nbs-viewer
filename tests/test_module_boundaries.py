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
    working_set,
)

PACKAGE = "nbs_viewer/models/plot"

#: Function-local sibling imports allowed to remain, as
#: ``(module, enclosing function, imported sibling)``.
#:
#: Empty, and meant to stay that way. It held three entries when this file
#: was written, all of them reaching into ``region_mesh`` for cell geometry
#: and together making up the whole frame <-> mask runtime cycle (then
#: ``plot_view_frame`` and ``region_mesh``); moving that geometry onto the
#: frame removed all three at
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

    ``geometry.mask.mask_from_vertices`` imports ``matplotlib.path`` in its
    body to keep a heavy optional dependency off the module's import path.
    That is a cost decision about a third-party package, not a cycle being
    concealed, so it must not be reported.
    """
    source = facts["geometry.mask"].path.read_text()
    assert "    from matplotlib.path import Path" in source, (
        "this test is only meaningful while region_mesh still defers a "
        "third-party import into a function body"
    )
    bodies = [
        imp
        for imp in function_local_imports(facts)
        if imp.module == "geometry.mask"
    ]
    assert bodies == []


def test_the_view_vocabulary_depends_on_nothing_in_the_package(facts):
    """
    ``view/`` is a sink: everything may import it, it imports nothing back.

    This is the property that makes it vocabulary rather than a layer. Every
    other package here describes data, fetches it or draws it, and all of
    them need these words -- so the words cannot need anything back without
    putting a cycle one edit away.

    It is also a useful smell test. Both times something in this package
    turned out to want a frame or a region, the thing that wanted it was not
    vocabulary: ``storage_axis_to_plot_axis`` was taking a frame it should
    never have had, and ``default_profile_label`` was ROI text.
    """
    outward = {
        (imp.module, imp.target)
        for imp in (i for m in facts.values() for i in m.imports)
        if imp.module.split(".")[0] == "view"
        and imp.target.split(".")[0] != "view"
    }
    assert outward == set(), f"view/ reaches outside itself: {sorted(outward)}"


# ---------------------------------------------------------------------------
# The detector itself, on a package small enough to read
# ---------------------------------------------------------------------------


def _write_package(root, files):
    """
    Write a throwaway package and return its directory.

    Keys may name a subdirectory (``"geo/frame.py"``), so a test can build a
    nested package and check that a relative import climbing out of it is
    resolved against the importing module's own position.
    """
    package = root / "sample_pkg"
    package.mkdir()
    for name, source in files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
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


def test_a_subpackage_module_is_found_and_named_by_its_path(tmp_path):
    """
    Modules below the package root are walked, not skipped.

    This matters because the whole point of phase 2 is to put these modules
    into subpackages. A guard that only globbed the top level would go quiet
    exactly when the tree it guards grows.
    """
    package = _write_package(
        tmp_path,
        {
            "top.py": "from .geo.frame import Frame\n",
            "geo/__init__.py": "",
            "geo/frame.py": "class Frame:\n    pass\n",
        },
    )
    facts = read_package(package)
    assert set(facts) == {"top", "geo", "geo.frame"}
    assert find_cycles(runtime_edges(facts)) == []


def test_a_relative_import_climbing_out_of_a_subpackage_resolves(tmp_path):
    """
    ``..`` is resolved against the importing module's position, not the root.
    """
    package = _write_package(
        tmp_path,
        {
            "vocab.py": "NAME = 'x'\n",
            "geo/__init__.py": "",
            "geo/frame.py": "from ..vocab import NAME\n",
            "geo/mask.py": "from .frame import NAME\n",
        },
    )
    facts = read_package(package)
    edges = runtime_edges(facts)
    assert edges["geo.frame"] == {"vocab"}
    assert edges["geo.mask"] == {"geo.frame"}


def test_a_cycle_across_a_subpackage_boundary_is_caught(tmp_path):
    """
    Splitting two modules into different subpackages does not hide a cycle.
    """
    package = _write_package(
        tmp_path,
        {
            "geo/__init__.py": "",
            "geo/frame.py": "from ..view.spec import Spec\n",
            "view/__init__.py": "",
            "view/spec.py": "from ..geo.frame import Frame\n",
        },
    )
    facts = read_package(package)
    assert find_cycles(runtime_edges(facts)) == [["geo.frame", "view.spec"]]


def test_a_package_init_is_a_module_like_any_other(tmp_path):
    """
    A surface that re-exports can close a cycle, so it is walked too.

    ``from . import x`` and ``from .geo import x`` both reach the same
    ``__init__``, which is why it is named by the package.
    """
    package = _write_package(
        tmp_path,
        {
            "geo/__init__.py": "from .frame import Frame\n",
            "geo/frame.py": "from . import Frame\n",
        },
    )
    facts = read_package(package)
    assert find_cycles(runtime_edges(facts)) == [["geo", "geo.frame"]]


def test_a_working_set_counts_through_a_re_export_surface(tmp_path):
    """
    A name taken from a package door is credited to the module behind it.

    Without this, moving files into subpackages would drive every working set
    toward zero while the reader's job got no smaller -- the diagnostic would
    report a win for the reorganisation that produced it. Classes still do
    not count, whichever way they are imported.
    """
    package = _write_package(
        tmp_path,
        {
            "geo/__init__.py": "from .bundle import Bundle, pack\n",
            "geo/bundle.py": """
                class Bundle:
                    pass


                def pack():
                    return Bundle()
                """,
            "caller.py": "from .geo import Bundle, pack\n",
        },
    )
    facts = read_package(package)
    functions, sources = working_set(facts, "caller")
    assert functions == {"pack"}
    assert sources == {"geo.bundle"}


def test_a_re_export_chain_does_not_loop_forever(tmp_path):
    """
    Two surfaces re-exporting from each other terminate rather than recurse.
    """
    package = _write_package(
        tmp_path,
        {
            "a/__init__.py": "from ..b import thing\n",
            "b/__init__.py": "from ..a import thing\n",
            "caller.py": "from .a import thing\n",
        },
    )
    facts = read_package(package)
    assert working_set(facts, "caller") == (set(), set())
