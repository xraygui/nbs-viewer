"""
Read a package's sibling imports out of its source, without importing it.

Two different questions are asked of the same parse. The *hard rules* -- no
runtime import cycle among siblings, and no function-local sibling import
used to dodge one -- are hazards, so a test asserts them. The *working set*
of a file, meaning how many sibling free functions it has to pull in, is a
diagnostic that locates smeared-out procedures; it is printed, never
asserted, because it is trivially gamed by moving free functions into a class
that is only a namespace.

Run as a script to print the table::

    pixi run python -m tools.module_graph
    pixi run python -m tools.module_graph nbs_viewer/models/cache
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The package these rules were written for.
DEFAULT_PACKAGE = "nbs_viewer/models/plot"


@dataclass(frozen=True)
class SiblingImport:
    """
    One import statement naming a module in the same package.

    Parameters
    ----------
    module : str
        Stem of the importing file, e.g. ``stages``.
    target : str
        Stem of the imported sibling, e.g. ``region_mesh``.
    names : tuple of str
        Names bound by the statement. Empty for ``import`` of the module
        itself rather than names out of it.
    lineno : int
        Line of the statement, for error messages.
    scope : str
        ``module`` for a plain top-level import, ``type_checking`` for one
        guarded by ``if TYPE_CHECKING``, or ``function`` for one inside a
        function body.
    function : str or None
        Dotted name of the enclosing function when ``scope`` is ``function``.
    """

    module: str
    target: str
    names: Tuple[str, ...]
    lineno: int
    scope: str
    function: Optional[str] = None

    @property
    def is_runtime(self) -> bool:
        """
        Return whether this import executes when the program runs.

        A ``TYPE_CHECKING`` import never does, so it cannot deadlock an
        import and does not count toward a cycle. A function-local one does,
        which is why moving an import into a function hides a cycle from the
        interpreter without removing it from the design.
        """
        return self.scope != "type_checking"

    def where(self) -> str:
        """
        Return a ``file:line`` style location with the enclosing function.
        """
        site = f"{self.module}.py:{self.lineno}"
        if self.function:
            site = f"{site} ({self.function})"
        return site


@dataclass
class ModuleFacts:
    """
    Everything one file in the package says about its siblings.

    Parameters
    ----------
    name : str
        Stem of the file.
    path : Path
        Path to the file.
    code_lines : int
        Lines that are neither blank, a comment, nor part of a docstring.
    free_functions : set of str
        Names of this module's own module-level functions, which is what
        makes an imported name count toward a working set.
    imports : list of SiblingImport
        Every sibling import found, in source order.
    """

    name: str
    path: Path
    code_lines: int
    free_functions: Set[str] = field(default_factory=set)
    imports: List[SiblingImport] = field(default_factory=list)


class _SiblingImportCollector(ast.NodeVisitor):
    """
    Collect sibling imports, tracking whether each one runs.

    Scope is tracked by descending the tree rather than by ``ast.walk``,
    because the distinction the hard rules turn on -- module level, inside a
    ``TYPE_CHECKING`` guard, inside a function -- is a property of where a
    node sits, which a flat walk throws away.
    """

    def __init__(
        self, module: str, home: str, siblings: Set[str], package: str
    ) -> None:
        self.module = module
        # The subpackage the file sits in, which a relative import counts
        # dots from. It cannot be derived from ``module``: a package's
        # ``__init__`` is named by the package it *is*, and also lives in it.
        self.home = home
        self.siblings = siblings
        self.package = package
        self.found: List[SiblingImport] = []
        self._functions: List[str] = []
        self._type_checking = False

    # -- scope tracking ---------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_test(node.test):
            was = self._type_checking
            self._type_checking = True
            for child in node.body:
                self.visit(child)
            self._type_checking = was
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    # -- the imports themselves -------------------------------------------

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        target = self._sibling_of_import_from(node)
        if target is not None:
            self._record(target, tuple(alias.name for alias in node.names), node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            target = self._sibling_of_dotted(alias.name)
            if target is not None:
                self._record(target, (), node)
        self.generic_visit(node)

    def _sibling_of_import_from(self, node: ast.ImportFrom) -> Optional[str]:
        """
        Return the module in this package a ``from ... import`` names.

        A relative import is resolved against the importing module's own
        position, so ``geometry/frame.py`` saying ``from .bundle import X``
        reaches ``geometry.bundle`` while ``from ..view_spec import Y``
        reaches ``view_spec``. ``from . import X`` names the package's own
        ``__init__``, which is a module here like any other.
        """
        if node.level == 0:
            return self._sibling_of_dotted(node.module) if node.module else None
        parts = self.home.split(".") if self.home else []
        ascend = node.level - 1
        if ascend > len(parts):
            return None
        base = parts[: len(parts) - ascend] if ascend else parts
        target = ".".join(base + ([node.module] if node.module else []))
        return target if target in self.siblings else None

    def _sibling_of_dotted(self, dotted: str) -> Optional[str]:
        """
        Return the module in this package an absolute dotted path names.
        """
        prefix = f"{self.package}."
        if dotted.startswith(prefix):
            tail = dotted[len(prefix) :]
            if tail in self.siblings:
                return tail
        return None

    def _record(
        self, target: str, names: Tuple[str, ...], node: ast.stmt
    ) -> None:
        if target == self.module:
            return
        if self._functions:
            scope = "function"
            function = ".".join(self._functions)
        elif self._type_checking:
            scope = "type_checking"
            function = None
        else:
            scope = "module"
            function = None
        self.found.append(
            SiblingImport(
                module=self.module,
                target=target,
                names=names,
                lineno=node.lineno,
                scope=scope,
                function=function,
            )
        )


def _is_type_checking_test(test: ast.expr) -> bool:
    """
    Return whether an ``if`` test is a ``TYPE_CHECKING`` guard.
    """
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _count_code_lines(source: str, tree: ast.Module) -> int:
    """
    Return lines that carry code rather than prose.

    Blank lines, whole-line comments and docstrings are excluded. This file's
    docstrings are long on purpose, so counting them would report the
    package's prose budget rather than the amount of code a reader has to
    hold, which is the thing the reorganisation is trying to shrink.
    """
    prose: Set[int] = set()
    for node in ast.walk(tree):
        # A lambda or conditional expression also has a ``body``, but it is a
        # single expression rather than a statement list.
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for child in body:
            if (
                isinstance(child, ast.Expr)
                and isinstance(child.value, ast.Constant)
                and isinstance(child.value.value, str)
            ):
                prose.update(range(child.lineno, (child.end_lineno or 0) + 1))

    total = 0
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or number in prose:
            continue
        total += 1
    return total


def read_package(package_dir) -> Dict[str, ModuleFacts]:
    """
    Parse every module in a package directory.

    Parameters
    ----------
    package_dir : Path or str
        Directory holding the package's ``.py`` files, absolute or relative
        to the repository root.

    Returns
    -------
    dict
        Module stem to :class:`ModuleFacts`, in sorted stem order.

    Raises
    ------
    FileNotFoundError
        If the directory holds no Python files.
    """
    package_dir = Path(package_dir)
    if not package_dir.is_absolute():
        package_dir = REPO_ROOT / package_dir
    paths = sorted(
        path
        for path in package_dir.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    if not paths:
        raise FileNotFoundError(f"No Python modules under {package_dir}")

    package = _dotted_name(package_dir)
    names = {path: _module_name(path, package_dir) for path in paths}
    siblings = set(names.values())

    facts: Dict[str, ModuleFacts] = {}
    for path in paths:
        name = names[path]
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        collector = _SiblingImportCollector(
            name, _home_package(path, package_dir), siblings, package
        )
        collector.visit(tree)
        facts[name] = ModuleFacts(
            name=name,
            path=path,
            code_lines=_count_code_lines(source, tree),
            free_functions={
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            },
            imports=collector.found,
        )
    return facts


def _home_package(path: Path, package_dir: Path) -> str:
    """
    Return the dotted subpackage a file sits in, relative to the root.

    ``geometry/frame.py`` and ``geometry/__init__.py`` both sit in
    ``geometry``; a file at the root sits in ``""``.
    """
    return ".".join(path.relative_to(package_dir).parent.parts)


def _module_name(path: Path, package_dir: Path) -> str:
    """
    Return a module's dotted name below the package root.

    ``geometry/frame.py`` is ``geometry.frame``; a package's ``__init__.py``
    is named by the package itself, because that is what ``from . import X``
    and ``from .geometry import X`` both reach.
    """
    relative = path.relative_to(package_dir)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = relative.stem
    return ".".join(parts)


def _dotted_name(package_dir: Path) -> str:
    """
    Return the dotted path a sibling would be imported by absolutely.

    Under the repository root that is the directory's position in it, so a
    file spelling ``nbs_viewer.models.plot.region_mesh`` instead of
    ``.region_mesh`` is still recognised as reaching a sibling. A directory
    outside the root -- a throwaway package in a test -- is named by itself,
    since there is no tree to place it in.
    """
    try:
        return ".".join(package_dir.relative_to(REPO_ROOT).parts)
    except ValueError:
        return package_dir.name


def runtime_edges(
    facts: Dict[str, ModuleFacts],
    ignore: Sequence[Tuple[str, Optional[str], str]] = (),
) -> Dict[str, Set[str]]:
    """
    Build the runtime sibling-import graph.

    Parameters
    ----------
    facts : dict
        Output of :func:`read_package`.
    ignore : sequence of tuple
        ``(module, function, target)`` triples to leave out, so a known
        function-local dodge reported by its own rule is not also reported
        as the cycle it creates.

    Returns
    -------
    dict
        Module stem to the set of siblings it imports at runtime.
    """
    ignored = set(ignore)
    graph: Dict[str, Set[str]] = {name: set() for name in facts}
    for module in facts.values():
        for imp in module.imports:
            if not imp.is_runtime:
                continue
            if (imp.module, imp.function, imp.target) in ignored:
                continue
            graph[imp.module].add(imp.target)
    return graph


def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """
    Return every elementary cycle in an import graph.

    Parameters
    ----------
    graph : dict
        Node to successors.

    Returns
    -------
    list of list of str
        One list of nodes per cycle, each starting at its smallest member so
        the same cycle is reported identically run to run. Sorted.
    """
    cycles: Set[Tuple[str, ...]] = set()
    path: List[str] = []
    on_path: Set[str] = set()

    def walk(node: str) -> None:
        path.append(node)
        on_path.add(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt in on_path:
                loop = path[path.index(nxt) :]
                pivot = loop.index(min(loop))
                cycles.add(tuple(loop[pivot:] + loop[:pivot]))
            else:
                walk(nxt)
        path.pop()
        on_path.discard(node)

    for start in sorted(graph):
        walk(start)
    return [list(cycle) for cycle in sorted(cycles)]


def mutual_pairs(facts: Dict[str, ModuleFacts]) -> List[Tuple[str, str]]:
    """
    Return sibling pairs that name each other, counting annotation imports.

    A pair where one direction is under ``TYPE_CHECKING`` is not a hazard and
    is often the right shape -- a controller naming the session that owns it,
    or a fetch naming the source it was handed. It is reported so a step can
    see where two modules are talking about each other at all. Longer mixed
    chains are deliberately not enumerated: one annotation edge closing a
    six-module runtime chain is arithmetic, not a finding.

    Parameters
    ----------
    facts : dict
        Output of :func:`read_package`.

    Returns
    -------
    list of tuple
        Sorted ``(left, right)`` pairs with ``left < right``.
    """
    named: Dict[str, Set[str]] = {name: set() for name in facts}
    for module in facts.values():
        for imp in module.imports:
            named[imp.module].add(imp.target)
    return sorted(
        (left, right)
        for left, targets in named.items()
        for right in targets
        if left < right and left in named.get(right, ())
    )


def function_local_imports(
    facts: Dict[str, ModuleFacts]
) -> List[SiblingImport]:
    """
    Return every sibling import that sits inside a function body.
    """
    return [
        imp
        for module in facts.values()
        for imp in module.imports
        if imp.scope == "function"
    ]


def working_set(
    facts: Dict[str, ModuleFacts], name: str
) -> Tuple[Set[str], Set[str]]:
    """
    Return the sibling free functions a module imports, and their homes.

    A module's working set is how many sibling *free functions* a reader has
    to go and find to learn what the module does. Imported classes and type
    aliases are excluded: a class travels with the behaviour that belongs to
    its data, which is the shape this plan wants, whereas a pile of imported
    free functions usually means one procedure has been smeared across
    several files.

    Function-local imports count toward the set as well -- a reader still
    has to go and find those functions -- and are also listed on their own,
    because hiding an import in a function body breaks a hard rule whatever
    it does to this number. Annotation-only imports do not count: a name
    used in a type hint says what a value is, not what this module does.

    Parameters
    ----------
    facts : dict
        Output of :func:`read_package`.
    name : str
        Module stem to measure.

    Returns
    -------
    tuple
        ``(imported function names, modules they came from)``.
    """
    functions: Set[str] = set()
    sources: Set[str] = set()
    for imp in facts[name].imports:
        if imp.scope == "type_checking":
            continue
        target = facts.get(imp.target)
        if target is None:
            continue
        hits = {
            imported
            for imported in imp.names
            if imported in target.free_functions
        }
        if hits:
            functions |= hits
            sources.add(imp.target)
    return functions, sources


def import_sites(package_dir) -> Dict[str, int]:
    """
    Count import statements naming this package, grouped by where they live.

    This is what a rename costs outside the package. Counting it before a
    move and after is how a step reports that it renamed a file without
    stranding a caller, and it is why the moves in this plan are safe: almost
    all of the sites are in the suite, which checks them immediately.

    Parameters
    ----------
    package_dir : Path or str
        Directory holding the package's ``.py`` files, absolute or relative
        to the repository root.

    Returns
    -------
    dict
        Directory to number of import statements, plus a ``"files"`` entry
        holding the number of distinct importing files and a ``"total"``
        entry.
    """
    package_dir = Path(package_dir)
    if not package_dir.is_absolute():
        package_dir = REPO_ROOT / package_dir
    dotted = ".".join(package_dir.relative_to(REPO_ROOT).parts)
    own = {path.resolve() for path in package_dir.glob("*.py")}

    skip = {".git", ".pixi", ".pytest_cache", "build", "dist", "oldtests"}
    counts: Dict[str, int] = {}
    files = 0
    total = 0
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if any(part in skip for part in relative.parts):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        here = sum(
            1
            for node in ast.walk(tree)
            for named in _modules_named(node, relative)
            if named == dotted or named.startswith(f"{dotted}.")
        )
        if not here:
            continue
        where = _importer_group(path, relative, own, package_dir)
        counts[where] = counts.get(where, 0) + here
        files += 1
        total += here
    counts["files"] = files
    counts["total"] = total
    return counts


def _importer_group(
    path: Path, relative: Path, own: Set[Path], package_dir: Path
) -> str:
    """
    Return the bucket an importing file is reported under.

    Files in the package itself are ``(inside)``. Everything else is grouped
    by its top-level directory, except within the shipped tree the package
    lives in, which is split one level deeper -- the interesting distinction
    there is views versus the rest of the models, and outside it a single
    row for the suite is enough.
    """
    if path.resolve() in own:
        return "(inside)"
    parts = relative.parent.parts
    if not parts:
        return "."
    shipped = package_dir.relative_to(REPO_ROOT).parts[0]
    depth = 2 if parts[0] == shipped else 1
    return "/".join(parts[:depth])


def _modules_named(node: ast.AST, relative: Path) -> List[str]:
    """
    Return the absolute module paths one import statement names.

    Relative imports are resolved against the importing file's own position,
    which matters here: ``views/`` reaches ``models/plot`` as
    ``from ...models.plot.run_source import RunSource``, and it also has a
    ``views/plot/`` package of its own, so a textual search for ``plot.``
    both misses real sites and invents ones that point somewhere else.

    Parameters
    ----------
    node : ast.AST
        Any node; non-import nodes yield nothing.
    relative : Path
        Path of the importing file relative to the repository root.

    Returns
    -------
    list of str
        Dotted module paths, one per name the statement reaches through.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    if node.level == 0:
        return [node.module] if node.module else []
    # ``level`` counts dots: one means this file's own package, two its
    # parent, and so on.
    package = list(relative.parent.parts)
    ascend = node.level - 1
    base = package[: len(package) - ascend] if ascend else package
    if ascend > len(package):
        return []
    return [".".join(base + ([node.module] if node.module else []))]


def format_report(
    facts: Dict[str, ModuleFacts], sites: Optional[Dict[str, int]] = None
) -> str:
    """
    Render the working-set table, the cycles, and the function-local dodges.

    Nothing here is a verdict. A working set that rises is not a regression:
    a step may legitimately concentrate related functions in one file, which
    is the point of concentrating them.

    Parameters
    ----------
    facts : dict
        Output of :func:`read_package`.
    sites : dict, optional
        Output of :func:`import_sites`, appended as a final section. It is
        consumed, not copied.
    """
    lines: List[str] = []

    total_code = sum(module.code_lines for module in facts.values())
    lines.append(f"{len(facts)} modules, {total_code} code lines")
    lines.append("")

    measured = []
    for name in facts:
        functions, sources = working_set(facts, name)
        locals_here = sum(
            1 for imp in facts[name].imports if imp.scope == "function"
        )
        measured.append((len(functions), name, facts[name].code_lines,
                         len(sources), locals_here, sorted(functions)))
    measured.sort(key=lambda row: (-row[0], row[1]))

    lines.append("Working sets -- sibling free functions imported")
    lines.append(
        f"{'module':<20}{'code':>6}{'free fns':>10}"
        f"{'modules':>9}{'fn-local':>10}"
    )
    zero = []
    for count, name, code, sources, locals_here, functions in measured:
        if count == 0 and locals_here == 0:
            zero.append(name)
            continue
        lines.append(
            f"{name:<20}{code:>6}{count:>10}{sources:>9}{locals_here:>10}"
        )
        lines.append(f"{'':<20}{', '.join(functions)}")
    if zero:
        lines.append("")
        lines.append(f"zero ({len(zero)}): {', '.join(zero)}")

    lines.append("")
    lines.append("Runtime cycles")
    cycles = find_cycles(runtime_edges(facts))
    if cycles:
        for cycle in cycles:
            lines.append("  " + " -> ".join(cycle + [cycle[0]]))
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Mutual pairs (either direction may be annotation-only)")
    for left, right in mutual_pairs(facts):
        lines.append(f"  {left} <-> {right}")

    lines.append("")
    lines.append("Function-local sibling imports")
    dodges = function_local_imports(facts)
    if dodges:
        for imp in sorted(dodges, key=lambda i: (i.module, i.lineno)):
            names = ", ".join(imp.names) or imp.target
            lines.append(f"  {imp.where()} -> {imp.target}: {names}")
    else:
        lines.append("  none")

    if sites is not None:
        lines.append("")
        total = sites.pop("total", 0)
        files = sites.pop("files", 0)
        lines.append(
            f"Import sites naming this package: {total} across {files} files"
        )
        for where, count in sorted(
            sites.items(), key=lambda row: (-row[1], row[0])
        ):
            lines.append(f"  {where:<12}{count:>5}")

    return "\n".join(lines)


def main(argv: Sequence[str]) -> int:
    """
    Print the report for a package named on the command line.
    """
    target = argv[1] if len(argv) > 1 else DEFAULT_PACKAGE
    print(f"# {target}")
    print(format_report(read_package(target), import_sites(target)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
