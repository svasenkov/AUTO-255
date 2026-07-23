"""Test meta-schema: language-agnostic intermediate representation.

This IR captures the essential structure of tests without language-specific
syntax. It maps directly to:
- Python pytest + allure
- Java JUnit5 + Allure
- TypeScript Vitest/Playwright + Allure
- C# NUnit/xUnit + Allure
- Go testing + allure-go

The schema is serializable to JSON for inspection and debugging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING


class AssertionType(Enum):
    """Universal assertion types mapped to each framework."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    TRUE = "true"
    FALSE = "false"
    NONE = "none"
    NOT_NONE = "not_none"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    RAISES = "raises"
    MATCHES_REGEX = "matches_regex"
    IS_INSTANCE = "is_instance"
    HAS_LENGTH = "has_length"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


class FixtureScope(Enum):
    """Fixture lifecycle scope."""
    FUNCTION = "function"  # per-test
    CLASS = "class"        # per-class
    MODULE = "module"      # per-file
    SESSION = "session"    # global


class PyramidLayer(Enum):
    """Test pyramid layer for CI matrix slicing."""
    UNIT = "unit"
    COMPONENT = "component"
    INTEGRATION = "integration"
    API = "api"
    E2E = "e2e"


@dataclass
class AllureMetadata:
    """Allure reporting metadata for a test or suite."""
    epic: str | None = None
    feature: str | None = None
    story: str | None = None
    title: str | None = None
    description: str | None = None
    severity: str | None = None  # blocker, critical, normal, minor, trivial
    parent_suite: str | None = None
    suite: str | None = None
    sub_suite: str | None = None
    tags: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)  # {type, url, name}
    testops_id: str | None = None


@dataclass
class Assertion:
    """Single assertion in a test step."""
    type: AssertionType
    actual: str  # expression/variable name
    expected: str | None = None  # for comparison assertions
    message: str | None = None


@dataclass
class TestStep:
    """Named step within a test (maps to allure.step)."""
    name: str
    description: str | None = None
    code_hint: str | None = None  # pseudo-code or key operation
    assertions: list[Assertion] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)  # {name, type, content_ref}


@dataclass
class ParameterSet:
    """Parameterized test data."""
    id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fixture:
    """Test fixture (setup/teardown resource)."""
    name: str
    scope: FixtureScope = FixtureScope.FUNCTION
    autouse: bool = False
    dependencies: list[str] = field(default_factory=list)  # other fixture names
    setup_hint: str | None = None  # pseudo-code for setup
    teardown_hint: str | None = None  # pseudo-code for teardown
    yields: str | None = None  # return type hint
    allure_title: str | None = None


@dataclass
class TestCase:
    """Single test case."""
    id: str  # unique identifier
    name: str  # function/method name
    allure: AllureMetadata = field(default_factory=AllureMetadata)
    layer: PyramidLayer = PyramidLayer.UNIT
    fixtures: list[str] = field(default_factory=list)  # fixture names used
    steps: list[TestStep] = field(default_factory=list)
    parameters: list[ParameterSet] = field(default_factory=list)  # for @pytest.mark.parametrize
    markers: list[str] = field(default_factory=list)  # pytest markers
    skip_reason: str | None = None
    xfail_reason: str | None = None
    timeout_seconds: float | None = None
    hypothesis_settings: dict[str, Any] | None = None  # for property-based tests


@dataclass
class TestModule:
    """Single test file/module."""
    name: str  # module name (e.g., test_router)
    path: str  # relative path
    allure: AllureMetadata = field(default_factory=AllureMetadata)  # module-level pytestmark
    fixtures: list[Fixture] = field(default_factory=list)
    tests: list[TestCase] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # key imports for context


@dataclass
class TestSuite:
    """Complete test suite (entire project)."""
    name: str
    version: str = "1.0.0"
    description: str | None = None
    source_language: str = "python"
    source_framework: str = "pytest"
    modules: list[TestModule] = field(default_factory=list)
    global_fixtures: list[Fixture] = field(default_factory=list)  # conftest.py fixtures
    config: dict[str, Any] = field(default_factory=dict)  # pytest.ini, pyproject.toml settings

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON for inspection."""
        def _serialize(obj: Any) -> Any:
            if isinstance(obj, Enum):
                return obj.value
            return str(obj)
        return json.dumps(asdict(self), indent=indent, default=_serialize)

    def to_file(self, path: Path) -> None:
        """Write meta-schema to JSON file."""
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_json(cls, data: str) -> TestSuite:
        """Deserialize from JSON."""
        raw = json.loads(data)
        return cls._from_dict(raw)

    @classmethod
    def from_file(cls, path: Path) -> TestSuite:
        """Load meta-schema from JSON file."""
        return cls.from_json(path.read_text(encoding="utf-8"))

    @classmethod
    def _from_dict(cls, d: dict) -> TestSuite:
        """Recursively reconstruct from dict."""
        modules = [
            TestModule(
                name=m["name"],
                path=m["path"],
                allure=AllureMetadata(**m.get("allure", {})),
                fixtures=[
                    Fixture(
                        name=f["name"],
                        scope=FixtureScope(f.get("scope", "function")),
                        autouse=f.get("autouse", False),
                        dependencies=f.get("dependencies", []),
                        setup_hint=f.get("setup_hint"),
                        teardown_hint=f.get("teardown_hint"),
                        yields=f.get("yields"),
                        allure_title=f.get("allure_title"),
                    )
                    for f in m.get("fixtures", [])
                ],
                tests=[
                    TestCase(
                        id=t["id"],
                        name=t["name"],
                        allure=AllureMetadata(**t.get("allure", {})),
                        layer=PyramidLayer(t.get("layer", "unit")),
                        fixtures=t.get("fixtures", []),
                        steps=[
                            TestStep(
                                name=s["name"],
                                description=s.get("description"),
                                code_hint=s.get("code_hint"),
                                assertions=[
                                    Assertion(
                                        type=AssertionType(a["type"]),
                                        actual=a["actual"],
                                        expected=a.get("expected"),
                                        message=a.get("message"),
                                    )
                                    for a in s.get("assertions", [])
                                ],
                                attachments=s.get("attachments", []),
                            )
                            for s in t.get("steps", [])
                        ],
                        parameters=[
                            ParameterSet(id=p.get("id"), values=p.get("values", {}))
                            for p in t.get("parameters", [])
                        ],
                        markers=t.get("markers", []),
                        skip_reason=t.get("skip_reason"),
                        xfail_reason=t.get("xfail_reason"),
                        timeout_seconds=t.get("timeout_seconds"),
                        hypothesis_settings=t.get("hypothesis_settings"),
                    )
                    for t in m.get("tests", [])
                ],
                imports=m.get("imports", []),
            )
            for m in d.get("modules", [])
        ]
        global_fixtures = [
            Fixture(
                name=f["name"],
                scope=FixtureScope(f.get("scope", "function")),
                autouse=f.get("autouse", False),
                dependencies=f.get("dependencies", []),
                setup_hint=f.get("setup_hint"),
                teardown_hint=f.get("teardown_hint"),
                yields=f.get("yields"),
                allure_title=f.get("allure_title"),
            )
            for f in d.get("global_fixtures", [])
        ]
        return cls(
            name=d["name"],
            version=d.get("version", "1.0.0"),
            description=d.get("description"),
            source_language=d.get("source_language", "python"),
            source_framework=d.get("source_framework", "pytest"),
            modules=modules,
            global_fixtures=global_fixtures,
            config=d.get("config", {}),
        )


# Target framework configurations
TARGETS = {
    # Java ecosystem
    "java-junit5-gradle": {
        "language": "java",
        "test_framework": "junit5",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "extensions": [".java"],
    },
    "java-junit5-maven": {
        "language": "java",
        "test_framework": "junit5",
        "build_tool": "maven",
        "allure_version": "2.25.0",
        "extensions": [".java"],
    },
    "java-testng-gradle": {
        "language": "java",
        "test_framework": "testng",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "extensions": [".java"],
    },
    # Kotlin
    "kotlin-junit5-gradle": {
        "language": "kotlin",
        "test_framework": "junit5",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "extensions": [".kt"],
    },
    "kotlin-kotest-gradle": {
        "language": "kotlin",
        "test_framework": "kotest",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "extensions": [".kt"],
    },
    # TypeScript/JavaScript
    "typescript-vitest": {
        "language": "typescript",
        "test_framework": "vitest",
        "build_tool": "npm",
        "allure_version": "3.0.0",
        "extensions": [".ts", ".spec.ts"],
    },
    "typescript-playwright": {
        "language": "typescript",
        "test_framework": "playwright",
        "build_tool": "npm",
        "allure_version": "3.0.0",
        "extensions": [".ts", ".spec.ts"],
    },
    "typescript-jest": {
        "language": "typescript",
        "test_framework": "jest",
        "build_tool": "npm",
        "allure_version": "3.0.0",
        "extensions": [".ts", ".test.ts"],
    },
    "javascript-mocha": {
        "language": "javascript",
        "test_framework": "mocha",
        "build_tool": "npm",
        "allure_version": "3.0.0",
        "extensions": [".js", ".spec.js"],
    },
    # C# / .NET
    "csharp-nunit": {
        "language": "csharp",
        "test_framework": "nunit",
        "build_tool": "dotnet",
        "allure_version": "2.25.0",
        "extensions": [".cs"],
    },
    "csharp-xunit": {
        "language": "csharp",
        "test_framework": "xunit",
        "build_tool": "dotnet",
        "allure_version": "2.25.0",
        "extensions": [".cs"],
    },
    "csharp-mstest": {
        "language": "csharp",
        "test_framework": "mstest",
        "build_tool": "dotnet",
        "allure_version": "2.25.0",
        "extensions": [".cs"],
    },
    # Go
    "go-testing": {
        "language": "go",
        "test_framework": "testing",
        "build_tool": "go",
        "allure_version": "2.25.0",
        "extensions": ["_test.go"],
    },
    "go-testify": {
        "language": "go",
        "test_framework": "testify",
        "build_tool": "go",
        "allure_version": "2.25.0",
        "extensions": ["_test.go"],
    },
    # Rust
    "rust-cargo": {
        "language": "rust",
        "test_framework": "cargo",
        "build_tool": "cargo",
        "allure_version": "2.25.0",
        "extensions": [".rs"],
    },
    # Ruby
    "ruby-rspec": {
        "language": "ruby",
        "test_framework": "rspec",
        "build_tool": "bundler",
        "allure_version": "2.25.0",
        "extensions": ["_spec.rb"],
    },
    "ruby-minitest": {
        "language": "ruby",
        "test_framework": "minitest",
        "build_tool": "bundler",
        "allure_version": "2.25.0",
        "extensions": ["_test.rb"],
    },
    # PHP
    "php-phpunit": {
        "language": "php",
        "test_framework": "phpunit",
        "build_tool": "composer",
        "allure_version": "2.25.0",
        "extensions": ["Test.php"],
    },
    "php-codeception": {
        "language": "php",
        "test_framework": "codeception",
        "build_tool": "composer",
        "allure_version": "2.25.0",
        "extensions": ["Cest.php"],
    },
    # Swift
    "swift-xctest": {
        "language": "swift",
        "test_framework": "xctest",
        "build_tool": "swift",
        "allure_version": "2.25.0",
        "extensions": [".swift"],
    },
    # Python (for migration/consistency)
    "python-pytest": {
        "language": "python",
        "test_framework": "pytest",
        "build_tool": "pip",
        "allure_version": "2.25.0",
        "extensions": ["test_*.py"],
    },
    # Scala
    "scala-scalatest": {
        "language": "scala",
        "test_framework": "scalatest",
        "build_tool": "sbt",
        "allure_version": "2.25.0",
        "extensions": [".scala"],
    },
    # ========== UI Testing Frameworks ==========
    # Selenium
    "java-selenium-junit5": {
        "language": "java",
        "test_framework": "selenium",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "ui_framework": "selenium",
        "extensions": [".java"],
    },
    "python-selenium-pytest": {
        "language": "python",
        "test_framework": "selenium",
        "build_tool": "pip",
        "allure_version": "2.25.0",
        "ui_framework": "selenium",
        "extensions": ["test_*.py"],
    },
    "csharp-selenium-nunit": {
        "language": "csharp",
        "test_framework": "selenium",
        "build_tool": "dotnet",
        "allure_version": "2.25.0",
        "ui_framework": "selenium",
        "extensions": [".cs"],
    },
    # Selenide (Java)
    "java-selenide-junit5": {
        "language": "java",
        "test_framework": "selenide",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "ui_framework": "selenide",
        "extensions": [".java"],
    },
    "java-selenide-testng": {
        "language": "java",
        "test_framework": "selenide",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "ui_framework": "selenide",
        "extensions": [".java"],
    },
    # Selene (Python)
    "python-selene-pytest": {
        "language": "python",
        "test_framework": "selene",
        "build_tool": "pip",
        "allure_version": "2.25.0",
        "ui_framework": "selene",
        "extensions": ["test_*.py"],
    },
    # Playwright (multi-language)
    "python-playwright-pytest": {
        "language": "python",
        "test_framework": "playwright",
        "build_tool": "pip",
        "allure_version": "2.25.0",
        "ui_framework": "playwright",
        "extensions": ["test_*.py"],
    },
    "java-playwright-junit5": {
        "language": "java",
        "test_framework": "playwright",
        "build_tool": "gradle",
        "allure_version": "2.25.0",
        "ui_framework": "playwright",
        "extensions": [".java"],
    },
    "csharp-playwright-nunit": {
        "language": "csharp",
        "test_framework": "playwright",
        "build_tool": "dotnet",
        "allure_version": "2.25.0",
        "ui_framework": "playwright",
        "extensions": [".cs"],
    },
    # Cypress (JavaScript)
    "javascript-cypress": {
        "language": "javascript",
        "test_framework": "cypress",
        "build_tool": "npm",
        "allure_version": "3.0.0",
        "ui_framework": "cypress",
        "extensions": [".cy.js"],
    },
    # WebdriverIO
    "typescript-webdriverio": {
        "language": "typescript",
        "test_framework": "webdriverio",
        "build_tool": "npm",
        "allure_version": "3.0.0",
        "ui_framework": "webdriverio",
        "extensions": [".ts"],
    },
}
