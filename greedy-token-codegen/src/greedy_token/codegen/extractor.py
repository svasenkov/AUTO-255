"""Extract test meta-schema from pytest test files using AST analysis.

Parses Python test files and extracts:
- Test functions and classes
- Fixtures (from conftest.py and test files)
- Allure decorators (@allure.epic, @allure.story, etc.)
- pytest markers (@pytest.mark.*)
- Hypothesis settings
- Step structure (from allure.step context managers)
- Assertions
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from greedy_token.codegen.schema import (
    AllureMetadata,
    Assertion,
    AssertionType,
    Fixture,
    FixtureScope,
    ParameterSet,
    PyramidLayer,
    TestCase,
    TestModule,
    TestStep,
    TestSuite,
)


def extract_from_pytest(
    tests_dir: Path,
    *,
    name: str = "extracted-suite",
    version: str = "1.0.0",
    description: str | None = None,
) -> TestSuite:
    """Extract meta-schema from a pytest test directory."""
    tests_path = Path(tests_dir)
    if not tests_path.is_dir():
        raise ValueError(f"Tests directory not found: {tests_path}")

    modules: list[TestModule] = []
    global_fixtures: list[Fixture] = []
    config: dict[str, Any] = {}

    conftest = tests_path / "conftest.py"
    if conftest.is_file():
        global_fixtures = _extract_fixtures(conftest)

    for test_file in sorted(tests_path.glob("test_*.py")):
        module = _extract_module(test_file, tests_path)
        if module.tests or module.fixtures:
            modules.append(module)

    pyproject = tests_path.parent / "pyproject.toml"
    if pyproject.is_file():
        config = _extract_pyproject_config(pyproject)

    return TestSuite(
        name=name,
        version=version,
        description=description,
        source_language="python",
        source_framework="pytest",
        modules=modules,
        global_fixtures=global_fixtures,
        config=config,
    )


def _extract_module(path: Path, base: Path) -> TestModule:
    """Extract test module from a single Python file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    module_name = path.stem
    rel_path = str(path.relative_to(base.parent))

    allure_meta = _extract_pytestmark_allure(tree)
    fixtures = _extract_fixtures(path)
    tests = _extract_tests(tree, module_name)
    imports = _extract_imports(tree)

    return TestModule(
        name=module_name,
        path=rel_path,
        allure=allure_meta,
        fixtures=fixtures,
        tests=tests,
        imports=imports,
    )


def _extract_pytestmark_allure(tree: ast.Module) -> AllureMetadata:
    """Extract module-level pytestmark allure decorators."""
    meta = AllureMetadata()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            _update_allure_from_call(elt, meta)
                    else:
                        _update_allure_from_call(node.value, meta)

    return meta


def _update_allure_from_call(node: ast.expr, meta: AllureMetadata) -> None:
    """Update AllureMetadata from an allure.* call."""
    if not isinstance(node, ast.Call):
        return

    func = node.func
    if isinstance(func, ast.Attribute):
        attr_name = func.attr
        if node.args:
            arg = node.args[0]
            value = _get_const_value(arg)
            if value is not None:
                if attr_name == "epic":
                    meta.epic = str(value)
                elif attr_name == "feature":
                    meta.feature = str(value)
                elif attr_name == "story":
                    meta.story = str(value)
                elif attr_name == "title":
                    meta.title = str(value)
                elif attr_name == "description":
                    meta.description = str(value)
                elif attr_name == "parent_suite":
                    meta.parent_suite = str(value)
                elif attr_name == "suite":
                    meta.suite = str(value)
                elif attr_name == "sub_suite":
                    meta.sub_suite = str(value)
                elif attr_name == "severity":
                    meta.severity = str(value)
                elif attr_name == "tag":
                    meta.tags.append(str(value))


def _get_const_value(node: ast.expr) -> Any:
    """Extract constant value from AST node."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Str):  # Python 3.7 compat
        return node.s
    if isinstance(node, ast.Num):  # Python 3.7 compat
        return node.n
    return None


def _extract_fixtures(path: Path) -> list[Fixture]:
    """Extract pytest fixtures from a file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    fixtures: list[Fixture] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            fixture_info = _get_fixture_decorator(node)
            if fixture_info:
                scope, autouse = fixture_info
                deps = _get_fixture_dependencies(node)
                allure_title = _get_allure_title(node)
                setup_hint, teardown_hint, yields = _analyze_fixture_body(node)

                fixtures.append(
                    Fixture(
                        name=node.name,
                        scope=scope,
                        autouse=autouse,
                        dependencies=deps,
                        setup_hint=setup_hint,
                        teardown_hint=teardown_hint,
                        yields=yields,
                        allure_title=allure_title,
                    )
                )

    return fixtures


def _get_fixture_decorator(node: ast.FunctionDef) -> tuple[FixtureScope, bool] | None:
    """Check if function is a pytest fixture and extract scope/autouse."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "fixture":
            return FixtureScope.FUNCTION, False
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "fixture":
                scope = FixtureScope.FUNCTION
                autouse = False
                for kw in dec.keywords:
                    if kw.arg == "scope":
                        scope_val = _get_const_value(kw.value)
                        if scope_val:
                            try:
                                scope = FixtureScope(scope_val)
                            except ValueError:
                                pass
                    elif kw.arg == "autouse":
                        autouse = bool(_get_const_value(kw.value))
                return scope, autouse
    return None


def _get_fixture_dependencies(node: ast.FunctionDef) -> list[str]:
    """Extract fixture dependencies from function arguments."""
    deps = []
    for arg in node.args.args:
        name = arg.arg
        if name not in ("self", "request", "tmp_path", "monkeypatch", "capsys", "capfd"):
            deps.append(name)
    return deps


def _get_allure_title(node: ast.FunctionDef) -> str | None:
    """Extract @allure.title from decorators."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "title":
                if dec.args:
                    return str(_get_const_value(dec.args[0]))
    return None


def _analyze_fixture_body(node: ast.FunctionDef) -> tuple[str | None, str | None, str | None]:
    """Analyze fixture body for setup/teardown/yield patterns."""
    has_yield = False
    setup_lines: list[str] = []
    teardown_lines: list[str] = []
    yields: str | None = None

    in_teardown = False
    for stmt in node.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Yield):
            has_yield = True
            in_teardown = True
            if stmt.value.value:
                yields = ast.unparse(stmt.value.value) if hasattr(ast, "unparse") else "value"
        elif has_yield and in_teardown:
            teardown_lines.append(_summarize_stmt(stmt))
        elif not in_teardown:
            setup_lines.append(_summarize_stmt(stmt))

    setup_hint = "; ".join(filter(None, setup_lines[:3])) or None
    teardown_hint = "; ".join(filter(None, teardown_lines[:3])) or None

    return setup_hint, teardown_hint, yields


def _summarize_stmt(stmt: ast.stmt) -> str:
    """Create a brief summary of a statement."""
    if isinstance(stmt, ast.Assign):
        targets = ", ".join(
            t.id if isinstance(t, ast.Name) else "..." for t in stmt.targets
        )
        return f"assign {targets}"
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        func = stmt.value.func
        if isinstance(func, ast.Attribute):
            return f"call {func.attr}"
        if isinstance(func, ast.Name):
            return f"call {func.id}"
    if isinstance(stmt, ast.If):
        return "if-block"
    if isinstance(stmt, ast.For):
        return "for-loop"
    if isinstance(stmt, ast.With):
        return "with-block"
    if isinstance(stmt, ast.Return):
        return "return"
    return ""


def _extract_tests(tree: ast.Module, module_name: str) -> list[TestCase]:
    """Extract test cases from AST."""
    tests: list[TestCase] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            test_case = _extract_test_case(node, module_name)
            tests.append(test_case)

    return tests


def _extract_test_case(node: ast.FunctionDef, module_name: str) -> TestCase:
    """Extract a single test case."""
    test_id = f"{module_name}::{node.name}"
    allure_meta = _extract_function_allure(node)
    layer = _infer_layer(module_name, node)
    fixtures = _get_fixture_dependencies(node)
    steps = _extract_steps(node)
    parameters = _extract_parameters(node)
    markers = _extract_markers(node)
    skip_reason = _get_skip_reason(node)
    xfail_reason = _get_xfail_reason(node)
    hypothesis = _extract_hypothesis_settings(node)

    return TestCase(
        id=test_id,
        name=node.name,
        allure=allure_meta,
        layer=layer,
        fixtures=fixtures,
        steps=steps,
        parameters=parameters,
        markers=markers,
        skip_reason=skip_reason,
        xfail_reason=xfail_reason,
        hypothesis_settings=hypothesis,
    )


def _extract_function_allure(node: ast.FunctionDef) -> AllureMetadata:
    """Extract allure decorators from a function."""
    meta = AllureMetadata()
    for dec in node.decorator_list:
        _update_allure_from_call(dec, meta)
    return meta


def _infer_layer(module_name: str, node: ast.FunctionDef) -> PyramidLayer:
    """Infer test pyramid layer from module name and markers."""
    name_lower = module_name.lower()
    if "e2e" in name_lower or "end_to_end" in name_lower:
        return PyramidLayer.E2E
    if "integration" in name_lower:
        return PyramidLayer.INTEGRATION
    if "api" in name_lower:
        return PyramidLayer.API
    if "component" in name_lower:
        return PyramidLayer.COMPONENT

    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "mark":
                if isinstance(func.value, ast.Attribute):
                    marker = func.value.attr
                    try:
                        return PyramidLayer(marker)
                    except ValueError:
                        pass

    return PyramidLayer.UNIT


def _extract_steps(node: ast.FunctionDef) -> list[TestStep]:
    """Extract allure.step blocks from test body."""
    steps: list[TestStep] = []

    for stmt in ast.walk(node):
        if isinstance(stmt, ast.With):
            for item in stmt.items:
                if isinstance(item.context_expr, ast.Call):
                    call = item.context_expr
                    func = call.func
                    if isinstance(func, ast.Attribute) and func.attr == "step":
                        step_name = ""
                        if call.args:
                            step_name = str(_get_const_value(call.args[0]) or "")

                        assertions = _extract_assertions_from_body(stmt.body)
                        code_hint = _summarize_step_body(stmt.body)

                        steps.append(
                            TestStep(
                                name=step_name,
                                assertions=assertions,
                                code_hint=code_hint,
                            )
                        )

    if not steps:
        assertions = _extract_assertions_from_body(node.body)
        if assertions:
            steps.append(
                TestStep(
                    name="Test body",
                    assertions=assertions,
                    code_hint=_summarize_step_body(node.body),
                )
            )

    return steps


def _extract_assertions_from_body(body: list[ast.stmt]) -> list[Assertion]:
    """Extract assertions from a block of statements."""
    assertions: list[Assertion] = []

    for stmt in body:
        if isinstance(stmt, ast.Assert):
            assertion = _parse_assert(stmt)
            if assertion:
                assertions.append(assertion)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            assertion = _parse_assert_call(stmt.value)
            if assertion:
                assertions.append(assertion)
        elif isinstance(stmt, ast.With):
            for item in stmt.items:
                if isinstance(item.context_expr, ast.Call):
                    func = item.context_expr.func
                    if isinstance(func, ast.Attribute) and func.attr == "raises":
                        exc_type = ""
                        if item.context_expr.args:
                            arg = item.context_expr.args[0]
                            if isinstance(arg, ast.Name):
                                exc_type = arg.id
                        assertions.append(
                            Assertion(
                                type=AssertionType.RAISES,
                                actual="block",
                                expected=exc_type,
                            )
                        )

    return assertions


def _parse_assert(stmt: ast.Assert) -> Assertion | None:
    """Parse a Python assert statement."""
    test = stmt.test
    msg = str(_get_const_value(stmt.msg)) if stmt.msg else None

    if isinstance(test, ast.Compare):
        if len(test.ops) == 1 and len(test.comparators) == 1:
            op = test.ops[0]
            left = ast.unparse(test.left) if hasattr(ast, "unparse") else "left"
            right = ast.unparse(test.comparators[0]) if hasattr(ast, "unparse") else "right"

            if isinstance(op, ast.Eq):
                return Assertion(AssertionType.EQUALS, left, right, msg)
            if isinstance(op, ast.NotEq):
                return Assertion(AssertionType.NOT_EQUALS, left, right, msg)
            if isinstance(op, ast.Gt):
                return Assertion(AssertionType.GREATER_THAN, left, right, msg)
            if isinstance(op, ast.Lt):
                return Assertion(AssertionType.LESS_THAN, left, right, msg)
            if isinstance(op, ast.GtE):
                return Assertion(AssertionType.GREATER_OR_EQUAL, left, right, msg)
            if isinstance(op, ast.LtE):
                return Assertion(AssertionType.LESS_OR_EQUAL, left, right, msg)
            if isinstance(op, ast.In):
                return Assertion(AssertionType.CONTAINS, right, left, msg)
            if isinstance(op, ast.NotIn):
                return Assertion(AssertionType.NOT_CONTAINS, right, left, msg)
            if isinstance(op, ast.Is) and isinstance(test.comparators[0], ast.Constant):
                if test.comparators[0].value is None:
                    return Assertion(AssertionType.NONE, left, None, msg)
                if test.comparators[0].value is True:
                    return Assertion(AssertionType.TRUE, left, None, msg)
                if test.comparators[0].value is False:
                    return Assertion(AssertionType.FALSE, left, None, msg)
            if isinstance(op, ast.IsNot) and isinstance(test.comparators[0], ast.Constant):
                if test.comparators[0].value is None:
                    return Assertion(AssertionType.NOT_NONE, left, None, msg)

    if isinstance(test, ast.Name):
        return Assertion(AssertionType.TRUE, test.id, None, msg)

    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        operand = ast.unparse(test.operand) if hasattr(ast, "unparse") else "expr"
        return Assertion(AssertionType.FALSE, operand, None, msg)

    return None


def _parse_assert_call(call: ast.Call) -> Assertion | None:
    """Parse assertThat-style calls (assertj, hamcrest patterns)."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None

    method = func.attr
    if method == "assertEqual" and len(call.args) >= 2:
        left = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else "left"
        right = ast.unparse(call.args[1]) if hasattr(ast, "unparse") else "right"
        return Assertion(AssertionType.EQUALS, left, right)

    if method == "assertTrue" and call.args:
        expr = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else "expr"
        return Assertion(AssertionType.TRUE, expr)

    if method == "assertFalse" and call.args:
        expr = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else "expr"
        return Assertion(AssertionType.FALSE, expr)

    if method == "assertIsNone" and call.args:
        expr = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else "expr"
        return Assertion(AssertionType.NONE, expr)

    if method == "assertIsNotNone" and call.args:
        expr = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else "expr"
        return Assertion(AssertionType.NOT_NONE, expr)

    if method == "assertIn" and len(call.args) >= 2:
        item = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else "item"
        container = ast.unparse(call.args[1]) if hasattr(ast, "unparse") else "container"
        return Assertion(AssertionType.CONTAINS, container, item)

    return None


def _summarize_step_body(body: list[ast.stmt]) -> str | None:
    """Create a brief summary of step operations."""
    summaries = []
    for stmt in body[:5]:
        summary = _summarize_stmt(stmt)
        if summary:
            summaries.append(summary)
    return "; ".join(summaries) if summaries else None


def _extract_parameters(node: ast.FunctionDef) -> list[ParameterSet]:
    """Extract @pytest.mark.parametrize data."""
    params: list[ParameterSet] = []

    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "parametrize":
                if len(dec.args) >= 2:
                    names_arg = dec.args[0]
                    values_arg = dec.args[1]

                    if isinstance(names_arg, ast.Constant):
                        names = [n.strip() for n in str(names_arg.value).split(",")]
                    elif isinstance(names_arg, (ast.List, ast.Tuple)):
                        names = [
                            str(_get_const_value(n)) for n in names_arg.elts
                        ]
                    else:
                        continue

                    if isinstance(values_arg, (ast.List, ast.Tuple)):
                        for i, val in enumerate(values_arg.elts):
                            if isinstance(val, (ast.List, ast.Tuple)):
                                values_dict = {}
                                for j, v in enumerate(val.elts):
                                    if j < len(names):
                                        values_dict[names[j]] = _get_const_value(v)
                                params.append(ParameterSet(id=f"param_{i}", values=values_dict))
                            else:
                                if names:
                                    params.append(
                                        ParameterSet(
                                            id=f"param_{i}",
                                            values={names[0]: _get_const_value(val)},
                                        )
                                    )

    return params


def _extract_markers(node: ast.FunctionDef) -> list[str]:
    """Extract pytest markers from decorators."""
    markers = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Attribute):
            if isinstance(dec.value, ast.Attribute) and dec.value.attr == "mark":
                markers.append(dec.attr)
        elif isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Attribute) and func.value.attr == "mark":
                    markers.append(func.attr)
    return markers


def _get_skip_reason(node: ast.FunctionDef) -> str | None:
    """Get skip reason from @pytest.mark.skip decorator."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr in ("skip", "skipif"):
                for kw in dec.keywords:
                    if kw.arg == "reason":
                        return str(_get_const_value(kw.value))
                if func.attr == "skip" and dec.args:
                    return str(_get_const_value(dec.args[0]))
    return None


def _get_xfail_reason(node: ast.FunctionDef) -> str | None:
    """Get xfail reason from @pytest.mark.xfail decorator."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "xfail":
                for kw in dec.keywords:
                    if kw.arg == "reason":
                        return str(_get_const_value(kw.value))
                if dec.args:
                    return str(_get_const_value(dec.args[0]))
    return None


def _extract_hypothesis_settings(node: ast.FunctionDef) -> dict[str, Any] | None:
    """Extract @hypothesis.settings or @given parameters."""
    settings: dict[str, Any] = {}

    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Name) and func.id == "given":
                settings["property_based"] = True
            elif isinstance(func, ast.Attribute) and func.attr == "settings":
                for kw in dec.keywords:
                    val = _get_const_value(kw.value)
                    if val is not None and kw.arg:
                        settings[kw.arg] = val

    return settings if settings else None


def _extract_imports(tree: ast.Module) -> list[str]:
    """Extract key imports for context."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return sorted(set(imports))


def _extract_pyproject_config(path: Path) -> dict[str, Any]:
    """Extract pytest config from pyproject.toml (basic parsing)."""
    config: dict[str, Any] = {}
    content = path.read_text(encoding="utf-8")

    markers_match = re.search(r'markers\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if markers_match:
        markers_text = markers_match.group(1)
        markers = re.findall(r'"([^"]+)"', markers_text)
        config["markers"] = markers

    testpaths_match = re.search(r'testpaths\s*=\s*\["([^"]+)"\]', content)
    if testpaths_match:
        config["testpaths"] = testpaths_match.group(1)

    return config
