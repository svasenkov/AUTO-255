"""Tests for the codegen module (cross-language test crystallization)."""

from __future__ import annotations

import json
from pathlib import Path

import allure
import pytest

from greedy_token.codegen.schema import (
    AllureMetadata,
    Assertion,
    AssertionType,
    Fixture,
    FixtureScope,
    PyramidLayer,
    TestCase,
    TestModule,
    TestStep,
    TestSuite,
    TARGETS,
)
from greedy_token.codegen.extractor import extract_from_pytest
from greedy_token.codegen.generator import generate_project

pytestmark = [
    allure.epic("Codegen"),
    allure.parent_suite("Codegen"),
    allure.feature("Cross-language crystallization"),
    allure.suite("Codegen"),
]


@allure.story("Schema")
@allure.title("TestSuite serializes to JSON and back")
def test_suite_json_roundtrip(tmp_path: Path) -> None:
    with allure.step("Create a TestSuite with all fields"):
        suite = TestSuite(
            name="test-suite",
            version="1.0.0",
            description="Test suite description",
            modules=[
                TestModule(
                    name="test_example",
                    path="tests/test_example.py",
                    allure=AllureMetadata(epic="Epic", feature="Feature"),
                    fixtures=[
                        Fixture(
                            name="my_fixture",
                            scope=FixtureScope.FUNCTION,
                            autouse=False,
                        )
                    ],
                    tests=[
                        TestCase(
                            id="test_example::test_one",
                            name="test_one",
                            allure=AllureMetadata(story="Story", title="Test One"),
                            layer=PyramidLayer.UNIT,
                            steps=[
                                TestStep(
                                    name="Step 1",
                                    assertions=[
                                        Assertion(
                                            type=AssertionType.EQUALS,
                                            actual="result",
                                            expected="expected",
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        )

    with allure.step("Serialize to JSON"):
        json_str = suite.to_json()
        assert "test-suite" in json_str
        assert "Epic" in json_str

    with allure.step("Write to file and read back"):
        out_path = tmp_path / "schema.json"
        suite.to_file(out_path)
        loaded = TestSuite.from_file(out_path)

    with allure.step("Verify roundtrip"):
        assert loaded.name == suite.name
        assert loaded.version == suite.version
        assert len(loaded.modules) == 1
        assert loaded.modules[0].name == "test_example"
        assert len(loaded.modules[0].tests) == 1
        assert loaded.modules[0].tests[0].name == "test_one"


@allure.story("Schema")
@allure.title("AllureMetadata captures all annotation types")
def test_allure_metadata_fields() -> None:
    with allure.step("Create metadata with all fields"):
        meta = AllureMetadata(
            epic="My Epic",
            feature="My Feature",
            story="My Story",
            title="My Title",
            description="My Description",
            severity="critical",
            parent_suite="Parent",
            suite="Suite",
            sub_suite="SubSuite",
            tags=["tag1", "tag2"],
            testops_id="12345",
        )

    with allure.step("Verify all fields"):
        assert meta.epic == "My Epic"
        assert meta.feature == "My Feature"
        assert meta.story == "My Story"
        assert meta.severity == "critical"
        assert meta.tags == ["tag1", "tag2"]
        assert meta.testops_id == "12345"


@allure.story("Schema")
@allure.title("TARGETS contains expected codegen targets")
def test_targets_catalog() -> None:
    with allure.step("Verify Java targets exist"):
        assert "java-junit5-gradle" in TARGETS
        assert "java-junit5-maven" in TARGETS
        assert TARGETS["java-junit5-gradle"]["language"] == "java"
        assert TARGETS["java-junit5-gradle"]["test_framework"] == "junit5"

    with allure.step("Verify TypeScript targets exist"):
        assert "typescript-vitest" in TARGETS
        assert "typescript-playwright" in TARGETS
        assert TARGETS["typescript-vitest"]["language"] == "typescript"

    with allure.step("Verify other language targets"):
        assert "csharp-nunit" in TARGETS
        assert "go-testing" in TARGETS


@allure.story("Extractor")
@allure.title("extract_from_pytest extracts module structure")
def test_extractor_basic(tmp_path: Path) -> None:
    with allure.step("Create minimal test file"):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text(
            '''
import pytest

def test_simple():
    assert 1 == 1

def test_with_assertion():
    result = 2 + 2
    assert result == 4
''',
            encoding="utf-8",
        )

    with allure.step("Extract meta-schema"):
        suite = extract_from_pytest(tests_dir, name="sample-suite")

    with allure.step("Verify extraction"):
        assert suite.name == "sample-suite"
        assert len(suite.modules) == 1
        assert suite.modules[0].name == "test_sample"
        assert len(suite.modules[0].tests) == 2
        test_names = [t.name for t in suite.modules[0].tests]
        assert "test_simple" in test_names
        assert "test_with_assertion" in test_names


@allure.story("Extractor")
@allure.title("extract_from_pytest extracts allure decorators")
def test_extractor_allure_decorators(tmp_path: Path) -> None:
    with allure.step("Create test file with allure decorators"):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_allure.py").write_text(
            '''
import allure
import pytest

pytestmark = [
    allure.epic("My Epic"),
    allure.feature("My Feature"),
]

@allure.story("My Story")
@allure.title("Test with allure decorators")
def test_decorated():
    with allure.step("First step"):
        assert True
    with allure.step("Second step"):
        result = 1 + 1
        assert result == 2
''',
            encoding="utf-8",
        )

    with allure.step("Extract meta-schema"):
        suite = extract_from_pytest(tests_dir, name="allure-suite")

    with allure.step("Verify module-level allure metadata"):
        module = suite.modules[0]
        assert module.allure.epic == "My Epic"
        assert module.allure.feature == "My Feature"

    with allure.step("Verify test-level allure metadata"):
        test = module.tests[0]
        assert test.allure.story == "My Story"
        assert test.allure.title == "Test with allure decorators"

    with allure.step("Verify steps extracted"):
        assert len(test.steps) >= 2
        step_names = [s.name for s in test.steps]
        assert "First step" in step_names
        assert "Second step" in step_names


@allure.story("Extractor")
@allure.title("extract_from_pytest extracts fixtures from conftest")
def test_extractor_fixtures(tmp_path: Path) -> None:
    with allure.step("Create conftest with fixtures"):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text(
            '''
import pytest
import allure

@allure.title("My fixture")
@pytest.fixture
def my_fixture():
    return "value"

@pytest.fixture(scope="session")
def session_fixture():
    yield "session"

@pytest.fixture(autouse=True)
def auto_fixture():
    pass
''',
            encoding="utf-8",
        )
        (tests_dir / "test_with_fixture.py").write_text(
            '''
def test_uses_fixture(my_fixture):
    assert my_fixture == "value"
''',
            encoding="utf-8",
        )

    with allure.step("Extract meta-schema"):
        suite = extract_from_pytest(tests_dir, name="fixture-suite")

    with allure.step("Verify global fixtures"):
        assert len(suite.global_fixtures) >= 3
        fixture_names = [f.name for f in suite.global_fixtures]
        assert "my_fixture" in fixture_names
        assert "session_fixture" in fixture_names
        assert "auto_fixture" in fixture_names

    with allure.step("Verify fixture properties"):
        session_fx = next(f for f in suite.global_fixtures if f.name == "session_fixture")
        assert session_fx.scope == FixtureScope.SESSION

        auto_fx = next(f for f in suite.global_fixtures if f.name == "auto_fixture")
        assert auto_fx.autouse is True


@allure.story("Generator")
@allure.title("generate_project creates Java JUnit5 Gradle project")
def test_generator_java_junit5_gradle(tmp_path: Path) -> None:
    with allure.step("Create minimal TestSuite"):
        suite = TestSuite(
            name="java-test-suite",
            version="1.0.0",
            modules=[
                TestModule(
                    name="test_router",
                    path="tests/test_router.py",
                    allure=AllureMetadata(epic="Routing", feature="Task router"),
                    tests=[
                        TestCase(
                            id="test_router::test_route_find",
                            name="test_route_find",
                            allure=AllureMetadata(
                                story="Tool tier",
                                title="Route find task to tool tier",
                            ),
                            steps=[
                                TestStep(
                                    name="Route find task",
                                    assertions=[
                                        Assertion(
                                            type=AssertionType.EQUALS,
                                            actual="decision.target",
                                            expected='"tool"',
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        )

    with allure.step("Generate Java project"):
        output_dir = tmp_path / "generated" / "java-junit5-gradle"
        report = generate_project(suite, "java-junit5-gradle", output_dir)

    with allure.step("Verify files created"):
        assert len(report["files_created"]) > 0
        assert (output_dir / "build.gradle").exists()
        assert (output_dir / "settings.gradle").exists()
        assert (output_dir / "src" / "test" / "java" / "tests" / "TestRouter.java").exists()
        assert (output_dir / "src" / "test" / "java" / "tests" / "TestBase.java").exists()

    with allure.step("Verify build.gradle content"):
        build_gradle = (output_dir / "build.gradle").read_text(encoding="utf-8")
        assert "io.qameta.allure" in build_gradle
        assert "junit.jupiter" in build_gradle
        assert "assertj" in build_gradle

    with allure.step("Verify test class content"):
        test_class = (output_dir / "src" / "test" / "java" / "tests" / "TestRouter.java").read_text(
            encoding="utf-8"
        )
        assert "public class TestRouter" in test_class
        assert "@Epic" in test_class or "@Feature" in test_class
        assert "@Test" in test_class
        assert "step(" in test_class


@allure.story("Generator")
@allure.title("generate_project creates TypeScript Vitest project")
def test_generator_typescript_vitest(tmp_path: Path) -> None:
    with allure.step("Create minimal TestSuite"):
        suite = TestSuite(
            name="ts-test-suite",
            version="1.0.0",
            modules=[
                TestModule(
                    name="test_api",
                    path="tests/test_api.py",
                    allure=AllureMetadata(epic="API", feature="REST API"),
                    tests=[
                        TestCase(
                            id="test_api::test_get_users",
                            name="test_get_users",
                            allure=AllureMetadata(
                                story="Users",
                                title="GET /users returns list",
                            ),
                            steps=[
                                TestStep(
                                    name="Send GET request",
                                    assertions=[
                                        Assertion(
                                            type=AssertionType.EQUALS,
                                            actual="response.status",
                                            expected="200",
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        )

    with allure.step("Generate TypeScript project"):
        output_dir = tmp_path / "generated" / "typescript-vitest"
        report = generate_project(suite, "typescript-vitest", output_dir)

    with allure.step("Verify files created"):
        assert len(report["files_created"]) > 0
        assert (output_dir / "package.json").exists()
        assert (output_dir / "vitest.config.ts").exists()
        assert (output_dir / "tests" / "test_api.spec.ts").exists()

    with allure.step("Verify package.json content"):
        pkg_json = json.loads((output_dir / "package.json").read_text(encoding="utf-8"))
        assert "vitest" in pkg_json["devDependencies"]
        assert "allure-vitest" in pkg_json["devDependencies"]

    with allure.step("Verify test file content"):
        test_file = (output_dir / "tests" / "test_api.spec.ts").read_text(encoding="utf-8")
        assert "describe(" in test_file
        assert "it(" in test_file
        assert "allure.step(" in test_file
        assert "expect(" in test_file


@allure.story("Generator")
@allure.title("generate_project respects overwrite flag")
def test_generator_overwrite_flag(tmp_path: Path) -> None:
    with allure.step("Create minimal TestSuite"):
        suite = TestSuite(name="overwrite-test", version="1.0.0", modules=[])

    output_dir = tmp_path / "generated"

    with allure.step("Generate first time"):
        report1 = generate_project(suite, "java-junit5-gradle", output_dir)
        assert len(report1["files_created"]) > 0
        assert len(report1["files_skipped"]) == 0

    with allure.step("Generate again without overwrite"):
        report2 = generate_project(suite, "java-junit5-gradle", output_dir, overwrite=False)
        assert len(report2["files_created"]) == 0
        assert len(report2["files_skipped"]) > 0

    with allure.step("Generate with overwrite"):
        report3 = generate_project(suite, "java-junit5-gradle", output_dir, overwrite=True)
        assert len(report3["files_created"]) > 0


@allure.story("Generator")
@allure.title("generate_project creates GitHub Actions workflow")
def test_generator_github_actions(tmp_path: Path) -> None:
    with allure.step("Create minimal TestSuite"):
        suite = TestSuite(name="ci-test", version="1.0.0", modules=[])

    with allure.step("Generate Java project"):
        output_dir = tmp_path / "generated"
        generate_project(suite, "java-junit5-gradle", output_dir)

    with allure.step("Verify workflow exists"):
        workflow = output_dir / ".github" / "workflows" / "test.yml"
        assert workflow.exists()

    with allure.step("Verify workflow content"):
        content = workflow.read_text(encoding="utf-8")
        assert "actions/checkout" in content
        assert "setup-java" in content
        assert "gradlew test" in content
        assert "allure" in content.lower()


@allure.story("Generator")
@allure.title("generate_project raises on unknown target")
def test_generator_unknown_target(tmp_path: Path) -> None:
    suite = TestSuite(name="test", version="1.0.0", modules=[])

    with allure.step("Attempt to generate with unknown target"):
        with pytest.raises(ValueError, match="Unknown target"):
            generate_project(suite, "unknown-target-xyz", tmp_path)


@allure.story("Assertions")
@allure.title("AssertionType maps to all common assertion patterns")
def test_assertion_type_completeness() -> None:
    with allure.step("Verify all common assertion types exist"):
        assert AssertionType.EQUALS
        assert AssertionType.NOT_EQUALS
        assert AssertionType.TRUE
        assert AssertionType.FALSE
        assert AssertionType.NONE
        assert AssertionType.NOT_NONE
        assert AssertionType.CONTAINS
        assert AssertionType.NOT_CONTAINS
        assert AssertionType.GREATER_THAN
        assert AssertionType.LESS_THAN
        assert AssertionType.RAISES
        assert AssertionType.MATCHES_REGEX
        assert AssertionType.IS_INSTANCE


@allure.story("PyramidLayer")
@allure.title("PyramidLayer covers test pyramid")
def test_pyramid_layer_completeness() -> None:
    with allure.step("Verify all pyramid layers exist"):
        assert PyramidLayer.UNIT
        assert PyramidLayer.COMPONENT
        assert PyramidLayer.INTEGRATION
        assert PyramidLayer.API
        assert PyramidLayer.E2E
