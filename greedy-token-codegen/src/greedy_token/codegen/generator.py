"""Generate test projects from meta-schema using Jinja2 templates.

This is the crystallization output: deterministic, reviewable code generation
with zero LLM cost per invocation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from greedy_token.codegen.schema import (
    AssertionType,
    Fixture,
    FixtureScope,
    PyramidLayer,
    TestCase,
    TestModule,
    TestSuite,
    TARGETS,
)

try:
    from jinja2 import Environment, PackageLoader, select_autoescape
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


def generate_project(
    suite: TestSuite,
    target: str,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate a test project from meta-schema.

    Returns generation report: files created, warnings, etc.
    """
    if target not in TARGETS:
        available = ", ".join(sorted(TARGETS.keys()))
        raise ValueError(f"Unknown target: {target}. Available: {available}")

    if not HAS_JINJA2:
        raise RuntimeError("Jinja2 required for codegen: pip install jinja2")

    target_config = TARGETS[target]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    generator_fn = _GENERATORS.get(target)
    if generator_fn is None:
        raise ValueError(f"Generator not implemented for target: {target}")

    return generator_fn(suite, target_config, output, overwrite=overwrite)


def _generate_java_junit5_gradle(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate Java JUnit5 + Gradle project."""
    report: dict[str, Any] = {
        "target": "java-junit5-gradle",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_gradle_files(suite, output, report, overwrite)
    _write_java_tests(suite, output, report, overwrite)
    _write_java_fixtures(suite, output, report, overwrite)
    _write_allure_config(output, report, overwrite)
    _write_github_actions_java(suite, output, report, overwrite)

    return report


def _write_gradle_files(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write build.gradle and settings.gradle."""
    build_gradle = output / "build.gradle"
    if build_gradle.exists() and not overwrite:
        report["files_skipped"].append(str(build_gradle))
    else:
        build_gradle.write_text(_JAVA_BUILD_GRADLE.format(
            project_name=_to_java_project_name(suite.name),
            description=suite.description or f"Generated from {suite.name}",
        ), encoding="utf-8")
        report["files_created"].append(str(build_gradle))

    settings_gradle = output / "settings.gradle"
    if settings_gradle.exists() and not overwrite:
        report["files_skipped"].append(str(settings_gradle))
    else:
        settings_gradle.write_text(
            f"rootProject.name = '{_to_java_project_name(suite.name)}'\n",
            encoding="utf-8",
        )
        report["files_created"].append(str(settings_gradle))


def _write_java_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Java test classes."""
    test_dir = output / "src" / "test" / "java" / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)

    for module in suite.modules:
        class_name = _to_java_class_name(module.name)
        file_path = test_dir / f"{class_name}.java"

        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_java_test_class(module, suite.global_fixtures)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))


def _write_java_fixtures(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Java fixture/base test class."""
    test_dir = output / "src" / "test" / "java" / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)

    base_file = test_dir / "TestBase.java"
    if base_file.exists() and not overwrite:
        report["files_skipped"].append(str(base_file))
    else:
        content = _generate_java_test_base(suite.global_fixtures)
        base_file.write_text(content, encoding="utf-8")
        report["files_created"].append(str(base_file))


def _write_allure_config(
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write allure.properties."""
    props_dir = output / "src" / "test" / "resources"
    props_dir.mkdir(parents=True, exist_ok=True)

    props_file = props_dir / "allure.properties"
    if props_file.exists() and not overwrite:
        report["files_skipped"].append(str(props_file))
    else:
        props_file.write_text(
            "allure.results.directory=build/allure-results\n",
            encoding="utf-8",
        )
        report["files_created"].append(str(props_file))


def _write_github_actions_java(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for Java tests."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        content = _JAVA_GITHUB_WORKFLOW.format(
            project_name=suite.name,
        )
        workflow_file.write_text(content, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _generate_java_test_class(module: TestModule, global_fixtures: list[Fixture]) -> str:
    """Generate a Java test class from a TestModule."""
    class_name = _to_java_class_name(module.name)

    imports = _JAVA_IMPORTS
    class_annotations = _generate_java_class_annotations(module.allure)

    methods = []
    for test in module.tests:
        method = _generate_java_test_method(test)
        methods.append(method)

    methods_str = "\n\n".join(methods)

    return f"""{imports}

{class_annotations}
public class {class_name} extends TestBase {{

{methods_str}
}}
"""


def _generate_java_class_annotations(allure: Any) -> str:
    """Generate Allure annotations for a class."""
    annotations = []
    if allure.epic:
        annotations.append(f'@Epic("{_escape_java(allure.epic)}")')
    if allure.feature:
        annotations.append(f'@Feature("{_escape_java(allure.feature)}")')
    if allure.parent_suite:
        annotations.append(f'@ParentSuite("{_escape_java(allure.parent_suite)}")')
    if allure.suite:
        annotations.append(f'@Suite("{_escape_java(allure.suite)}")')
    return "\n".join(annotations) if annotations else ""


def _generate_java_test_method(test: TestCase) -> str:
    """Generate a Java test method from a TestCase."""
    method_name = _to_java_method_name(test.name)
    annotations = _generate_java_method_annotations(test)

    steps_code = []
    for step in test.steps:
        step_code = _generate_java_step(step)
        steps_code.append(step_code)

    body = "\n".join(steps_code) if steps_code else "        // TODO: implement test"

    return f"""{annotations}
    @Test
    void {method_name}() {{
{body}
    }}"""


def _generate_java_method_annotations(test: TestCase) -> str:
    """Generate Allure/JUnit annotations for a method."""
    annotations = []

    if test.allure.story:
        annotations.append(f'    @Story("{_escape_java(test.allure.story)}")')
    if test.allure.title:
        annotations.append(f'    @DisplayName("{_escape_java(test.allure.title)}")')
    if test.allure.description:
        annotations.append(f'    @Description("{_escape_java(test.allure.description)}")')
    if test.allure.severity:
        severity = test.allure.severity.upper()
        annotations.append(f'    @Severity(SeverityLevel.{severity})')

    for tag in test.allure.tags:
        annotations.append(f'    @Tag("{_escape_java(tag)}")')

    if test.skip_reason:
        annotations.append(f'    @Disabled("{_escape_java(test.skip_reason)}")')

    return "\n".join(annotations) if annotations else ""


def _generate_java_step(step: Any) -> str:
    """Generate Java code for an allure step."""
    step_name = _escape_java(step.name)
    assertions_code = []

    for assertion in step.assertions:
        assertion_code = _generate_java_assertion(assertion)
        if assertion_code:
            assertions_code.append(f"            {assertion_code}")

    if assertions_code:
        assertions_str = "\n".join(assertions_code)
        return f'''        step("{step_name}", () -> {{
{assertions_str}
        }});'''
    else:
        hint = step.code_hint or "// implement step logic"
        return f'''        step("{step_name}", () -> {{
            {hint}
        }});'''


def _generate_java_assertion(assertion: Any) -> str:
    """Generate Java assertion code."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"assertThat({actual}).isEqualTo({expected});",
        AssertionType.NOT_EQUALS: f"assertThat({actual}).isNotEqualTo({expected});",
        AssertionType.TRUE: f"assertThat({actual}).isTrue();",
        AssertionType.FALSE: f"assertThat({actual}).isFalse();",
        AssertionType.NONE: f"assertThat({actual}).isNull();",
        AssertionType.NOT_NONE: f"assertThat({actual}).isNotNull();",
        AssertionType.CONTAINS: f"assertThat({actual}).contains({expected});",
        AssertionType.NOT_CONTAINS: f"assertThat({actual}).doesNotContain({expected});",
        AssertionType.GREATER_THAN: f"assertThat({actual}).isGreaterThan({expected});",
        AssertionType.LESS_THAN: f"assertThat({actual}).isLessThan({expected});",
        AssertionType.GREATER_OR_EQUAL: f"assertThat({actual}).isGreaterThanOrEqualTo({expected});",
        AssertionType.LESS_OR_EQUAL: f"assertThat({actual}).isLessThanOrEqualTo({expected});",
        AssertionType.IS_EMPTY: f"assertThat({actual}).isEmpty();",
        AssertionType.IS_NOT_EMPTY: f"assertThat({actual}).isNotEmpty();",
        AssertionType.HAS_LENGTH: f"assertThat({actual}).hasSize({expected});",
        AssertionType.MATCHES_REGEX: f'assertThat({actual}).matches("{expected}");',
        AssertionType.IS_INSTANCE: f"assertThat({actual}).isInstanceOf({expected}.class);",
        AssertionType.RAISES: f"assertThatThrownBy(() -> {{ /* {actual} */ }}).isInstanceOf({expected}.class);",
    }

    return mapping.get(assertion.type, f"// TODO: {assertion.type.value} assertion")


def _generate_java_test_base(fixtures: list[Fixture]) -> str:
    """Generate TestBase class with global fixtures."""
    before_all = []
    after_each = []
    fields = []

    for fixture in fixtures:
        if fixture.scope == FixtureScope.SESSION:
            if fixture.setup_hint:
                before_all.append(f"        // {fixture.name}: {fixture.setup_hint}")
        elif fixture.autouse:
            if fixture.teardown_hint:
                after_each.append(f"        // {fixture.name}: {fixture.teardown_hint}")

    before_all_code = "\n".join(before_all) if before_all else "        // Global setup"
    after_each_code = "\n".join(after_each) if after_each else "        // Cleanup"

    return f"""{_JAVA_IMPORTS}

@ExtendWith(AllureJunit5.class)
public class TestBase {{

    @BeforeAll
    static void setUpAll() {{
{before_all_code}
    }}

    @AfterEach
    void tearDown() {{
{after_each_code}
    }}
}}
"""


def _generate_typescript_vitest(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate TypeScript Vitest project."""
    report: dict[str, Any] = {
        "target": "typescript-vitest",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_package_json(suite, output, report, overwrite)
    _write_vitest_config(output, report, overwrite)
    _write_ts_tests(suite, output, report, overwrite)
    _write_github_actions_ts(suite, output, report, overwrite)

    return report


def _write_package_json(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write package.json for TypeScript project."""
    pkg_file = output / "package.json"
    if pkg_file.exists() and not overwrite:
        report["files_skipped"].append(str(pkg_file))
    else:
        content = _TS_PACKAGE_JSON.format(
            name=_to_npm_name(suite.name),
            description=suite.description or f"Generated from {suite.name}",
        )
        pkg_file.write_text(content, encoding="utf-8")
        report["files_created"].append(str(pkg_file))


def _write_vitest_config(
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write vitest.config.ts."""
    config_file = output / "vitest.config.ts"
    if config_file.exists() and not overwrite:
        report["files_skipped"].append(str(config_file))
    else:
        config_file.write_text(_TS_VITEST_CONFIG, encoding="utf-8")
        report["files_created"].append(str(config_file))


def _write_ts_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write TypeScript test files."""
    test_dir = output / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)

    for module in suite.modules:
        file_name = f"{module.name}.spec.ts"
        file_path = test_dir / file_name

        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_ts_test_file(module)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))


def _write_github_actions_ts(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for TypeScript tests."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        content = _TS_GITHUB_WORKFLOW.format(project_name=suite.name)
        workflow_file.write_text(content, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _generate_ts_test_file(module: TestModule) -> str:
    """Generate a TypeScript test file."""
    imports = "import { describe, it, expect, beforeAll, afterEach } from 'vitest';\nimport * as allure from 'allure-js-commons';\n"

    describe_name = _escape_ts(module.allure.feature or module.name)
    tests_code = []

    for test in module.tests:
        test_code = _generate_ts_test(test)
        tests_code.append(test_code)

    tests_str = "\n\n".join(tests_code)

    labels = []
    if module.allure.epic:
        labels.append(f"  allure.epic('{_escape_ts(module.allure.epic)}');")
    if module.allure.feature:
        labels.append(f"  allure.feature('{_escape_ts(module.allure.feature)}');")

    labels_str = "\n".join(labels)
    labels_block = f"\n  beforeAll(() => {{\n{labels_str}\n  }});\n" if labels else ""

    return f"""{imports}
describe('{describe_name}', () => {{{labels_block}
{tests_str}
}});
"""


def _generate_ts_test(test: TestCase) -> str:
    """Generate a TypeScript test from TestCase."""
    test_name = _escape_ts(test.allure.title or test.name)

    steps_code = []
    for step in test.steps:
        step_code = _generate_ts_step(step)
        steps_code.append(step_code)

    body = "\n".join(steps_code) if steps_code else "    // TODO: implement test"

    labels = []
    if test.allure.story:
        labels.append(f"    allure.story('{_escape_ts(test.allure.story)}');")

    labels_str = "\n".join(labels)
    labels_block = f"{labels_str}\n" if labels else ""

    skip_prefix = "it.skip" if test.skip_reason else "it"

    return f"""  {skip_prefix}('{test_name}', async () => {{
{labels_block}{body}
  }});"""


def _generate_ts_step(step: Any) -> str:
    """Generate TypeScript step code."""
    step_name = _escape_ts(step.name)

    assertions_code = []
    for assertion in step.assertions:
        assertion_code = _generate_ts_assertion(assertion)
        if assertion_code:
            assertions_code.append(f"      {assertion_code}")

    if assertions_code:
        assertions_str = "\n".join(assertions_code)
        return f"""    await allure.step('{step_name}', async () => {{
{assertions_str}
    }});"""
    else:
        hint = step.code_hint or "// implement step logic"
        return f"""    await allure.step('{step_name}', async () => {{
      {hint}
    }});"""


def _generate_ts_assertion(assertion: Any) -> str:
    """Generate TypeScript/Vitest assertion code."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"expect({actual}).toBe({expected});",
        AssertionType.NOT_EQUALS: f"expect({actual}).not.toBe({expected});",
        AssertionType.TRUE: f"expect({actual}).toBe(true);",
        AssertionType.FALSE: f"expect({actual}).toBe(false);",
        AssertionType.NONE: f"expect({actual}).toBeNull();",
        AssertionType.NOT_NONE: f"expect({actual}).not.toBeNull();",
        AssertionType.CONTAINS: f"expect({actual}).toContain({expected});",
        AssertionType.NOT_CONTAINS: f"expect({actual}).not.toContain({expected});",
        AssertionType.GREATER_THAN: f"expect({actual}).toBeGreaterThan({expected});",
        AssertionType.LESS_THAN: f"expect({actual}).toBeLessThan({expected});",
        AssertionType.GREATER_OR_EQUAL: f"expect({actual}).toBeGreaterThanOrEqual({expected});",
        AssertionType.LESS_OR_EQUAL: f"expect({actual}).toBeLessThanOrEqual({expected});",
        AssertionType.IS_EMPTY: f"expect({actual}).toHaveLength(0);",
        AssertionType.IS_NOT_EMPTY: f"expect({actual}.length).toBeGreaterThan(0);",
        AssertionType.HAS_LENGTH: f"expect({actual}).toHaveLength({expected});",
        AssertionType.MATCHES_REGEX: f"expect({actual}).toMatch(/{expected}/);",
        AssertionType.IS_INSTANCE: f"expect({actual}).toBeInstanceOf({expected});",
        AssertionType.RAISES: f"expect(() => {{ /* {actual} */ }}).toThrow({expected});",
    }

    return mapping.get(assertion.type, f"// TODO: {assertion.type.value} assertion")


def _to_java_class_name(name: str) -> str:
    """Convert module name to Java class name."""
    parts = name.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def _to_java_method_name(name: str) -> str:
    """Convert test name to Java method name."""
    name = re.sub(r"^test_", "", name)
    return _to_camel_case(name)


def _to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _to_java_project_name(name: str) -> str:
    """Convert name to valid Gradle project name."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", name).lower()


def _to_npm_name(name: str) -> str:
    """Convert name to valid npm package name."""
    return re.sub(r"[^a-z0-9-]", "-", name.lower())


def _escape_java(s: str) -> str:
    """Escape string for Java."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_ts(s: str) -> str:
    """Escape string for TypeScript/JavaScript."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


_JAVA_IMPORTS = """package tests;

import io.qameta.allure.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.extension.ExtendWith;
import io.qameta.allure.junit5.AllureJunit5;

import static io.qameta.allure.Allure.step;
import static org.assertj.core.api.Assertions.*;"""


_JAVA_BUILD_GRADLE = """plugins {{
    id 'java'
    id 'io.qameta.allure' version '2.11.2'
}}

group = 'tests'
version = '1.0.0'
description = '{description}'

repositories {{
    mavenCentral()
}}

def allureVersion = '2.25.0'
def junitVersion = '5.10.1'

dependencies {{
    testImplementation "org.junit.jupiter:junit-jupiter:$junitVersion"
    testImplementation "io.qameta.allure:allure-junit5:$allureVersion"
    testImplementation 'org.assertj:assertj-core:3.24.2'
}}

allure {{
    version = allureVersion
    autoconfigure = true
    aspectjweaver = true
}}

test {{
    useJUnitPlatform()
    testLogging {{
        events 'passed', 'skipped', 'failed'
    }}
}}

tasks.withType(JavaCompile) {{
    options.encoding = 'UTF-8'
}}
"""


_JAVA_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Setup Gradle
        uses: gradle/actions/setup-gradle@v3

      - name: Run tests
        run: ./gradlew test

      - name: Generate Allure Report
        if: always()
        run: ./gradlew allureReport

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: build/allure-results
"""


_TS_PACKAGE_JSON = """{{
  "name": "{name}",
  "version": "1.0.0",
  "description": "{description}",
  "type": "module",
  "scripts": {{
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage",
    "allure:generate": "allure generate ./allure-results -o ./allure-report --clean",
    "allure:serve": "allure serve ./allure-results"
  }},
  "devDependencies": {{
    "vitest": "^2.0.0",
    "allure-vitest": "^3.0.0",
    "allure-js-commons": "^3.0.0",
    "@vitest/coverage-v8": "^2.0.0",
    "typescript": "^5.4.0"
  }}
}}
"""


_TS_VITEST_CONFIG = """import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    reporters: ['default', ['allure-vitest/reporter', { resultsDir: './allure-results' }]],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
  },
});
"""


_TS_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Run tests
        run: npm test

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: allure-results
"""


def _generate_csharp_nunit(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate C# NUnit project."""
    report: dict[str, Any] = {
        "target": "csharp-nunit",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_csharp_project(suite, output, report, overwrite)
    _write_csharp_tests(suite, output, report, overwrite)
    _write_github_actions_dotnet(suite, output, report, overwrite)

    return report


def _write_csharp_project(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write .csproj file."""
    csproj = output / f"{_to_pascal_case(suite.name)}.Tests.csproj"
    if csproj.exists() and not overwrite:
        report["files_skipped"].append(str(csproj))
    else:
        csproj.write_text(_CSHARP_CSPROJ, encoding="utf-8")
        report["files_created"].append(str(csproj))


def _write_csharp_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write C# test files."""
    test_dir = output / "Tests"
    test_dir.mkdir(parents=True, exist_ok=True)

    for module in suite.modules:
        class_name = _to_pascal_case(module.name)
        file_path = test_dir / f"{class_name}.cs"

        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_csharp_test_class(module)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))


def _generate_csharp_test_class(module: TestModule) -> str:
    """Generate C# NUnit test class."""
    class_name = _to_pascal_case(module.name)

    methods = []
    for test in module.tests:
        method = _generate_csharp_test_method(test)
        methods.append(method)

    methods_str = "\n\n".join(methods)

    allure_attrs = []
    if module.allure.epic:
        allure_attrs.append(f'[AllureEpic("{_escape_csharp(module.allure.epic)}")]')
    if module.allure.feature:
        allure_attrs.append(f'[AllureFeature("{_escape_csharp(module.allure.feature)}")]')

    attrs_str = "\n".join(allure_attrs)

    return f"""using NUnit.Framework;
using Allure.Net.Commons;
using NUnit.Allure.Attributes;
using NUnit.Allure.Core;

namespace Tests;

[TestFixture]
[AllureNUnit]
{attrs_str}
public class {class_name}
{{
{methods_str}
}}
"""


def _generate_csharp_test_method(test: TestCase) -> str:
    """Generate C# NUnit test method."""
    method_name = _to_pascal_case(test.name)

    attrs = []
    if test.allure.story:
        attrs.append(f'    [AllureStory("{_escape_csharp(test.allure.story)}")]')
    if test.allure.title:
        attrs.append(f'    [Test(Description = "{_escape_csharp(test.allure.title)}")]')
    else:
        attrs.append("    [Test]")

    if test.skip_reason:
        attrs.append(f'    [Ignore("{_escape_csharp(test.skip_reason)}")]')

    attrs_str = "\n".join(attrs)

    steps_code = []
    for step in test.steps:
        step_code = _generate_csharp_step(step)
        steps_code.append(step_code)

    body = "\n".join(steps_code) if steps_code else "        // TODO: implement test"

    return f"""{attrs_str}
    public void {method_name}()
    {{
{body}
    }}"""


def _generate_csharp_step(step: Any) -> str:
    """Generate C# Allure step."""
    step_name = _escape_csharp(step.name)

    assertions_code = []
    for assertion in step.assertions:
        code = _generate_csharp_assertion(assertion)
        if code:
            assertions_code.append(f"            {code}")

    if assertions_code:
        assertions_str = "\n".join(assertions_code)
        return f'''        AllureApi.Step("{step_name}", () =>
        {{
{assertions_str}
        }});'''
    else:
        hint = step.code_hint or "// implement step logic"
        return f'''        AllureApi.Step("{step_name}", () =>
        {{
            {hint}
        }});'''


def _generate_csharp_assertion(assertion: Any) -> str:
    """Generate C# NUnit assertion."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"Assert.That({actual}, Is.EqualTo({expected}));",
        AssertionType.NOT_EQUALS: f"Assert.That({actual}, Is.Not.EqualTo({expected}));",
        AssertionType.TRUE: f"Assert.That({actual}, Is.True);",
        AssertionType.FALSE: f"Assert.That({actual}, Is.False);",
        AssertionType.NONE: f"Assert.That({actual}, Is.Null);",
        AssertionType.NOT_NONE: f"Assert.That({actual}, Is.Not.Null);",
        AssertionType.CONTAINS: f"Assert.That({actual}, Does.Contain({expected}));",
        AssertionType.NOT_CONTAINS: f"Assert.That({actual}, Does.Not.Contain({expected}));",
        AssertionType.GREATER_THAN: f"Assert.That({actual}, Is.GreaterThan({expected}));",
        AssertionType.LESS_THAN: f"Assert.That({actual}, Is.LessThan({expected}));",
    }

    return mapping.get(assertion.type, f"// TODO: {assertion.type.value}")


def _write_github_actions_dotnet(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for .NET."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        workflow_file.write_text(_CSHARP_GITHUB_WORKFLOW, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _generate_go_testing(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate Go testing project."""
    report: dict[str, Any] = {
        "target": "go-testing",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_go_mod(suite, output, report, overwrite)
    _write_go_tests(suite, output, report, overwrite)
    _write_github_actions_go(suite, output, report, overwrite)

    return report


def _write_go_mod(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write go.mod file."""
    go_mod = output / "go.mod"
    if go_mod.exists() and not overwrite:
        report["files_skipped"].append(str(go_mod))
    else:
        mod_name = _to_go_module_name(suite.name)
        go_mod.write_text(f"""module {mod_name}

go 1.21

require (
    github.com/stretchr/testify v1.9.0
    github.com/dailymotion/allure-go v0.7.0
)
""", encoding="utf-8")
        report["files_created"].append(str(go_mod))


def _write_go_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Go test files."""
    for module in suite.modules:
        file_name = f"{_to_snake_case(module.name)}_test.go"
        file_path = output / file_name

        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_go_test_file(module)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))


def _generate_go_test_file(module: TestModule) -> str:
    """Generate Go test file."""
    pkg_name = _to_snake_case(module.name).replace("test_", "")

    tests = []
    for test in module.tests:
        test_code = _generate_go_test_func(test)
        tests.append(test_code)

    tests_str = "\n\n".join(tests)

    return f"""package {pkg_name}_test

import (
    "testing"

    "github.com/stretchr/testify/assert"
    "github.com/dailymotion/allure-go"
)

{tests_str}
"""


def _generate_go_test_func(test: TestCase) -> str:
    """Generate Go test function."""
    func_name = _to_pascal_case(test.name)

    steps_code = []
    for step in test.steps:
        step_code = _generate_go_step(step)
        steps_code.append(step_code)

    body = "\n".join(steps_code) if steps_code else "\t// TODO: implement test"

    allure_setup = []
    if test.allure.epic:
        allure_setup.append(f'\tallure.Epic("{_escape_go(test.allure.epic)}")')
    if test.allure.feature:
        allure_setup.append(f'\tallure.Feature("{_escape_go(test.allure.feature)}")')
    if test.allure.story:
        allure_setup.append(f'\tallure.Story("{_escape_go(test.allure.story)}")')

    setup_str = "\n".join(allure_setup)

    skip_code = ""
    if test.skip_reason:
        skip_code = f'\n\tt.Skip("{_escape_go(test.skip_reason)}")'

    return f"""func {func_name}(t *testing.T) {{
{setup_str}{skip_code}
{body}
}}"""


def _generate_go_step(step: Any) -> str:
    """Generate Go allure step."""
    step_name = _escape_go(step.name)

    assertions_code = []
    for assertion in step.assertions:
        code = _generate_go_assertion(assertion)
        if code:
            assertions_code.append(f"\t\t{code}")

    if assertions_code:
        assertions_str = "\n".join(assertions_code)
        return f'''\tallure.Step(allure.Description("{step_name}"), func() {{
{assertions_str}
\t}})'''
    else:
        hint = step.code_hint or "// implement step logic"
        return f'''\tallure.Step(allure.Description("{step_name}"), func() {{
\t\t{hint}
\t}})'''


def _generate_go_assertion(assertion: Any) -> str:
    """Generate Go testify assertion."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"assert.Equal(t, {expected}, {actual})",
        AssertionType.NOT_EQUALS: f"assert.NotEqual(t, {expected}, {actual})",
        AssertionType.TRUE: f"assert.True(t, {actual})",
        AssertionType.FALSE: f"assert.False(t, {actual})",
        AssertionType.NONE: f"assert.Nil(t, {actual})",
        AssertionType.NOT_NONE: f"assert.NotNil(t, {actual})",
        AssertionType.CONTAINS: f"assert.Contains(t, {actual}, {expected})",
        AssertionType.NOT_CONTAINS: f"assert.NotContains(t, {actual}, {expected})",
        AssertionType.GREATER_THAN: f"assert.Greater(t, {actual}, {expected})",
        AssertionType.LESS_THAN: f"assert.Less(t, {actual}, {expected})",
    }

    return mapping.get(assertion.type, f"// TODO: {assertion.type.value}")


def _write_github_actions_go(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for Go."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        workflow_file.write_text(_GO_GITHUB_WORKFLOW, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _generate_rust_cargo(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate Rust cargo test project."""
    report: dict[str, Any] = {
        "target": "rust-cargo",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_cargo_toml(suite, output, report, overwrite)
    _write_rust_tests(suite, output, report, overwrite)
    _write_github_actions_rust(suite, output, report, overwrite)

    return report


def _write_cargo_toml(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Cargo.toml."""
    cargo_toml = output / "Cargo.toml"
    if cargo_toml.exists() and not overwrite:
        report["files_skipped"].append(str(cargo_toml))
    else:
        name = _to_snake_case(suite.name).replace("-", "_")
        cargo_toml.write_text(f"""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dev-dependencies]
pretty_assertions = "1.4"

[[test]]
name = "tests"
path = "tests/mod.rs"
""", encoding="utf-8")
        report["files_created"].append(str(cargo_toml))


def _write_rust_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Rust test files."""
    tests_dir = output / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    mod_content = []
    for module in suite.modules:
        mod_name = _to_snake_case(module.name).replace("test_", "")
        mod_content.append(f"mod {mod_name};")

        file_path = tests_dir / f"{mod_name}.rs"
        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_rust_test_module(module)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))

    mod_file = tests_dir / "mod.rs"
    if not mod_file.exists() or overwrite:
        mod_file.write_text("\n".join(mod_content) + "\n", encoding="utf-8")
        report["files_created"].append(str(mod_file))


def _generate_rust_test_module(module: TestModule) -> str:
    """Generate Rust test module."""
    tests = []
    for test in module.tests:
        test_code = _generate_rust_test_func(test)
        tests.append(test_code)

    tests_str = "\n\n".join(tests)

    return f"""use pretty_assertions::assert_eq;

{tests_str}
"""


def _generate_rust_test_func(test: TestCase) -> str:
    """Generate Rust test function."""
    func_name = _to_snake_case(test.name)

    assertions_code = []
    for step in test.steps:
        for assertion in step.assertions:
            code = _generate_rust_assertion(assertion)
            if code:
                assertions_code.append(f"    {code}")

    body = "\n".join(assertions_code) if assertions_code else "    // TODO: implement test"

    ignore = "#[ignore]\n" if test.skip_reason else ""
    doc = f'/// {test.allure.title or test.name}\n' if test.allure.title else ""

    return f"""{doc}{ignore}#[test]
fn {func_name}() {{
{body}
}}"""


def _generate_rust_assertion(assertion: Any) -> str:
    """Generate Rust assertion."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"assert_eq!({actual}, {expected});",
        AssertionType.NOT_EQUALS: f"assert_ne!({actual}, {expected});",
        AssertionType.TRUE: f"assert!({actual});",
        AssertionType.FALSE: f"assert!(!{actual});",
        AssertionType.NONE: f"assert!({actual}.is_none());",
        AssertionType.NOT_NONE: f"assert!({actual}.is_some());",
        AssertionType.CONTAINS: f'assert!({actual}.contains({expected}));',
        AssertionType.GREATER_THAN: f"assert!({actual} > {expected});",
        AssertionType.LESS_THAN: f"assert!({actual} < {expected});",
    }

    return mapping.get(assertion.type, f"// TODO: {assertion.type.value}")


def _write_github_actions_rust(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for Rust."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        workflow_file.write_text(_RUST_GITHUB_WORKFLOW, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _generate_ruby_rspec(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate Ruby RSpec project."""
    report: dict[str, Any] = {
        "target": "ruby-rspec",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_gemfile(suite, output, report, overwrite)
    _write_rspec_helper(output, report, overwrite)
    _write_ruby_tests(suite, output, report, overwrite)
    _write_github_actions_ruby(suite, output, report, overwrite)

    return report


def _write_gemfile(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Gemfile."""
    gemfile = output / "Gemfile"
    if gemfile.exists() and not overwrite:
        report["files_skipped"].append(str(gemfile))
    else:
        gemfile.write_text(_RUBY_GEMFILE, encoding="utf-8")
        report["files_created"].append(str(gemfile))


def _write_rspec_helper(
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write spec_helper.rb."""
    spec_dir = output / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)

    helper = spec_dir / "spec_helper.rb"
    if helper.exists() and not overwrite:
        report["files_skipped"].append(str(helper))
    else:
        helper.write_text(_RUBY_SPEC_HELPER, encoding="utf-8")
        report["files_created"].append(str(helper))


def _write_ruby_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write Ruby RSpec test files."""
    spec_dir = output / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)

    for module in suite.modules:
        file_name = f"{_to_snake_case(module.name)}_spec.rb"
        file_path = spec_dir / file_name

        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_ruby_spec_file(module)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))


def _generate_ruby_spec_file(module: TestModule) -> str:
    """Generate Ruby RSpec file."""
    describe_name = module.allure.feature or module.name

    tests = []
    for test in module.tests:
        test_code = _generate_ruby_spec(test)
        tests.append(test_code)

    tests_str = "\n\n".join(tests)

    return f"""# frozen_string_literal: true

require 'spec_helper'

RSpec.describe '{describe_name}' do
{tests_str}
end
"""


def _generate_ruby_spec(test: TestCase) -> str:
    """Generate Ruby RSpec example."""
    test_name = test.allure.title or test.name

    steps_code = []
    for step in test.steps:
        step_code = _generate_ruby_step(step)
        steps_code.append(step_code)

    body = "\n".join(steps_code) if steps_code else "    # TODO: implement test"

    skip = ", skip: true" if test.skip_reason else ""

    return f"""  it '{_escape_ruby(test_name)}'{skip} do
{body}
  end"""


def _generate_ruby_step(step: Any) -> str:
    """Generate Ruby RSpec step (using Allure)."""
    step_name = _escape_ruby(step.name)

    assertions_code = []
    for assertion in step.assertions:
        code = _generate_ruby_assertion(assertion)
        if code:
            assertions_code.append(f"      {code}")

    if assertions_code:
        assertions_str = "\n".join(assertions_code)
        return f'''    Allure.step('{step_name}') do
{assertions_str}
    end'''
    else:
        hint = step.code_hint or "# implement step logic"
        return f'''    Allure.step('{step_name}') do
      {hint}
    end'''


def _generate_ruby_assertion(assertion: Any) -> str:
    """Generate Ruby RSpec assertion."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"expect({actual}).to eq({expected})",
        AssertionType.NOT_EQUALS: f"expect({actual}).not_to eq({expected})",
        AssertionType.TRUE: f"expect({actual}).to be true",
        AssertionType.FALSE: f"expect({actual}).to be false",
        AssertionType.NONE: f"expect({actual}).to be_nil",
        AssertionType.NOT_NONE: f"expect({actual}).not_to be_nil",
        AssertionType.CONTAINS: f"expect({actual}).to include({expected})",
        AssertionType.NOT_CONTAINS: f"expect({actual}).not_to include({expected})",
        AssertionType.GREATER_THAN: f"expect({actual}).to be > {expected}",
        AssertionType.LESS_THAN: f"expect({actual}).to be < {expected}",
    }

    return mapping.get(assertion.type, f"# TODO: {assertion.type.value}")


def _write_github_actions_ruby(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for Ruby."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        workflow_file.write_text(_RUBY_GITHUB_WORKFLOW, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _generate_php_phpunit(
    suite: TestSuite,
    config: dict[str, Any],
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate PHP PHPUnit project."""
    report: dict[str, Any] = {
        "target": "php-phpunit",
        "files_created": [],
        "files_skipped": [],
        "warnings": [],
    }

    _write_composer_json(suite, output, report, overwrite)
    _write_phpunit_xml(output, report, overwrite)
    _write_php_tests(suite, output, report, overwrite)
    _write_github_actions_php(suite, output, report, overwrite)

    return report


def _write_composer_json(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write composer.json."""
    composer = output / "composer.json"
    if composer.exists() and not overwrite:
        report["files_skipped"].append(str(composer))
    else:
        name = _to_snake_case(suite.name).replace("_", "-")
        composer.write_text(_PHP_COMPOSER_JSON.format(name=name), encoding="utf-8")
        report["files_created"].append(str(composer))


def _write_phpunit_xml(
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write phpunit.xml."""
    phpunit = output / "phpunit.xml"
    if phpunit.exists() and not overwrite:
        report["files_skipped"].append(str(phpunit))
    else:
        phpunit.write_text(_PHP_PHPUNIT_XML, encoding="utf-8")
        report["files_created"].append(str(phpunit))


def _write_php_tests(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write PHP test files."""
    tests_dir = output / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    for module in suite.modules:
        class_name = _to_pascal_case(module.name) + "Test"
        file_path = tests_dir / f"{class_name}.php"

        if file_path.exists() and not overwrite:
            report["files_skipped"].append(str(file_path))
            continue

        content = _generate_php_test_class(module)
        file_path.write_text(content, encoding="utf-8")
        report["files_created"].append(str(file_path))


def _generate_php_test_class(module: TestModule) -> str:
    """Generate PHP PHPUnit test class."""
    class_name = _to_pascal_case(module.name) + "Test"

    methods = []
    for test in module.tests:
        method = _generate_php_test_method(test)
        methods.append(method)

    methods_str = "\n\n".join(methods)

    return f"""<?php

declare(strict_types=1);

namespace Tests;

use PHPUnit\\Framework\\TestCase;
use Qameta\\Allure\\Allure;
use Qameta\\Allure\\Attribute\\Epic;
use Qameta\\Allure\\Attribute\\Feature;
use Qameta\\Allure\\Attribute\\Story;

#[Epic('{_escape_php(module.allure.epic or "")}')]
#[Feature('{_escape_php(module.allure.feature or "")}')]
final class {class_name} extends TestCase
{{
{methods_str}
}}
"""


def _generate_php_test_method(test: TestCase) -> str:
    """Generate PHP PHPUnit test method."""
    method_name = _to_camel_case(test.name)

    attrs = []
    if test.allure.story:
        attrs.append(f"    #[Story('{_escape_php(test.allure.story)}')]")

    attrs_str = "\n".join(attrs) + "\n" if attrs else ""

    steps_code = []
    for step in test.steps:
        step_code = _generate_php_step(step)
        steps_code.append(step_code)

    body = "\n".join(steps_code) if steps_code else "        // TODO: implement test"

    return f"""{attrs_str}    public function {method_name}(): void
    {{
{body}
    }}"""


def _generate_php_step(step: Any) -> str:
    """Generate PHP Allure step."""
    step_name = _escape_php(step.name)

    assertions_code = []
    for assertion in step.assertions:
        code = _generate_php_assertion(assertion)
        if code:
            assertions_code.append(f"            {code}")

    if assertions_code:
        assertions_str = "\n".join(assertions_code)
        return f'''        Allure::runStep(static function (): void {{
{assertions_str}
        }}, '{step_name}');'''
    else:
        hint = step.code_hint or "// implement step logic"
        return f'''        Allure::runStep(static function (): void {{
            {hint}
        }}, '{step_name}');'''


def _generate_php_assertion(assertion: Any) -> str:
    """Generate PHP PHPUnit assertion."""
    actual = assertion.actual
    expected = assertion.expected

    mapping = {
        AssertionType.EQUALS: f"$this->assertEquals({expected}, {actual});",
        AssertionType.NOT_EQUALS: f"$this->assertNotEquals({expected}, {actual});",
        AssertionType.TRUE: f"$this->assertTrue({actual});",
        AssertionType.FALSE: f"$this->assertFalse({actual});",
        AssertionType.NONE: f"$this->assertNull({actual});",
        AssertionType.NOT_NONE: f"$this->assertNotNull({actual});",
        AssertionType.CONTAINS: f"$this->assertStringContainsString({expected}, {actual});",
        AssertionType.GREATER_THAN: f"$this->assertGreaterThan({expected}, {actual});",
        AssertionType.LESS_THAN: f"$this->assertLessThan({expected}, {actual});",
    }

    return mapping.get(assertion.type, f"// TODO: {assertion.type.value}")


def _write_github_actions_php(
    suite: TestSuite,
    output: Path,
    report: dict[str, Any],
    overwrite: bool,
) -> None:
    """Write GitHub Actions workflow for PHP."""
    workflows_dir = output / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / "test.yml"
    if workflow_file.exists() and not overwrite:
        report["files_skipped"].append(str(workflow_file))
    else:
        workflow_file.write_text(_PHP_GITHUB_WORKFLOW, encoding="utf-8")
        report["files_created"].append(str(workflow_file))


def _to_pascal_case(name: str) -> str:
    """Convert to PascalCase."""
    name = re.sub(r"^test_", "", name)
    parts = name.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def _to_snake_case(name: str) -> str:
    """Convert to snake_case."""
    name = re.sub(r"([A-Z])", r"_\1", name).lower()
    name = re.sub(r"[-\s]+", "_", name)
    return re.sub(r"_+", "_", name).strip("_")


def _to_go_module_name(name: str) -> str:
    """Convert to Go module name."""
    return "github.com/example/" + _to_snake_case(name).replace("_", "-")


def _escape_csharp(s: str) -> str:
    """Escape for C#."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_go(s: str) -> str:
    """Escape for Go."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_ruby(s: str) -> str:
    """Escape for Ruby."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def _escape_php(s: str) -> str:
    """Escape for PHP."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


_CSHARP_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
    <Nullable>enable</Nullable>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="NUnit" Version="4.0.1" />
    <PackageReference Include="NUnit3TestAdapter" Version="4.5.0" />
    <PackageReference Include="Allure.NUnit" Version="2.12.0" />
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.9.0" />
  </ItemGroup>

</Project>
"""


_CSHARP_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'

      - name: Restore
        run: dotnet restore

      - name: Test
        run: dotnet test --logger "trx" --results-directory TestResults

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: allure-results
"""


_GO_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Go
        uses: actions/setup-go@v5
        with:
          go-version: '1.21'

      - name: Get dependencies
        run: go mod download

      - name: Test
        run: go test -v ./...

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: allure-results
"""


_RUST_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Rust
        uses: dtolnay/rust-action@stable

      - name: Test
        run: cargo test --verbose

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: allure-results
"""


_RUBY_GEMFILE = """source 'https://rubygems.org'

gem 'rspec', '~> 3.12'
gem 'allure-rspec', '~> 2.23'
"""


_RUBY_SPEC_HELPER = """require 'allure-rspec'

AllureRspec.configure do |config|
  config.results_directory = 'allure-results'
  config.clean_results_directory = true
end

RSpec.configure do |config|
  config.formatter = AllureRspecFormatter
end
"""


_RUBY_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Ruby
        uses: ruby/setup-ruby@v1
        with:
          ruby-version: '3.2'
          bundler-cache: true

      - name: Install dependencies
        run: bundle install

      - name: Test
        run: bundle exec rspec

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: allure-results
"""


_PHP_COMPOSER_JSON = """{{
  "name": "tests/{name}",
  "require-dev": {{
    "phpunit/phpunit": "^10.5",
    "allure-framework/allure-phpunit": "^2.0"
  }},
  "autoload-dev": {{
    "psr-4": {{
      "Tests\\\\": "tests/"
    }}
  }}
}}
"""


_PHP_PHPUNIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<phpunit xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:noNamespaceSchemaLocation="vendor/phpunit/phpunit/phpunit.xsd"
         colors="true"
         bootstrap="vendor/autoload.php">
    <testsuites>
        <testsuite name="Tests">
            <directory>tests</directory>
        </testsuite>
    </testsuites>
    <extensions>
        <extension class="Qameta\\Allure\\PHPUnit\\AllureExtension">
            <arguments>
                <string>allure-results</string>
            </arguments>
        </extension>
    </extensions>
</phpunit>
"""


_PHP_GITHUB_WORKFLOW = """name: Tests

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup PHP
        uses: shivammathur/setup-php@v2
        with:
          php-version: '8.3'
          tools: composer

      - name: Install dependencies
        run: composer install

      - name: Test
        run: vendor/bin/phpunit

      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: allure-results
"""


_GENERATORS = {
    # Java ecosystem
    "java-junit5-gradle": _generate_java_junit5_gradle,
    "java-junit5-maven": _generate_java_junit5_gradle,
    "java-testng-gradle": _generate_java_junit5_gradle,
    # Kotlin
    "kotlin-junit5-gradle": _generate_java_junit5_gradle,
    "kotlin-kotest-gradle": _generate_java_junit5_gradle,
    # TypeScript/JavaScript
    "typescript-vitest": _generate_typescript_vitest,
    "typescript-playwright": _generate_typescript_vitest,
    "typescript-jest": _generate_typescript_vitest,
    "javascript-mocha": _generate_typescript_vitest,
    # C# / .NET
    "csharp-nunit": _generate_csharp_nunit,
    "csharp-xunit": _generate_csharp_nunit,
    "csharp-mstest": _generate_csharp_nunit,
    # Go
    "go-testing": _generate_go_testing,
    "go-testify": _generate_go_testing,
    # Rust
    "rust-cargo": _generate_rust_cargo,
    # Ruby
    "ruby-rspec": _generate_ruby_rspec,
    "ruby-minitest": _generate_ruby_rspec,
    # PHP
    "php-phpunit": _generate_php_phpunit,
    "php-codeception": _generate_php_phpunit,
    # Python (roundtrip)
    "python-pytest": _generate_typescript_vitest,  # TODO: proper Python generator
    # Scala
    "scala-scalatest": _generate_java_junit5_gradle,
}
