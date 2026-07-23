"""Cross-language test code generation via crystallization.

Extracts test meta-schema from pytest tests and generates equivalent test
suites in other languages/frameworks. Philosophy: crystallize once, generate
deterministically — no LLM cost per generation.

Usage:
    greedy-token codegen --target java-junit5-gradle --output ./generated
    greedy-token codegen --list-targets
    greedy-token codegen --extract tests/ --output meta-schema.json
"""

from greedy_token.codegen.schema import (
    TestSuite,
    TestCase,
    TestStep,
    Fixture,
    Assertion,
    AllureMetadata,
)
from greedy_token.codegen.extractor import extract_from_pytest
from greedy_token.codegen.generator import generate_project

__all__ = [
    "TestSuite",
    "TestCase",
    "TestStep",
    "Fixture",
    "Assertion",
    "AllureMetadata",
    "extract_from_pytest",
    "generate_project",
]
