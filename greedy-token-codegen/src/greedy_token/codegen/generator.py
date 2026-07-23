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


_GENERATORS = {
    "java-junit5-gradle": _generate_java_junit5_gradle,
    "java-junit5-maven": _generate_java_junit5_gradle,  # Same logic, different build file
    "kotlin-junit5-gradle": _generate_java_junit5_gradle,  # TODO: Kotlin-specific
    "typescript-vitest": _generate_typescript_vitest,
    "typescript-playwright": _generate_typescript_vitest,  # TODO: Playwright-specific
}
