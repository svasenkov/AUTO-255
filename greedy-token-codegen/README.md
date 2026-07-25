# greedy-token codegen

Cross-language test code generation via crystallization.

## Philosophy

This module extends greedy-token's crystallization approach to code generation:

- **Extract once**: Parse pytest tests into a language-agnostic meta-schema
- **Generate deterministically**: Template-based generation with zero LLM cost
- **Same input → same output**: Reproducible, reviewable, revertible

```
                    greedy-token Python tests
                              │
                    (1) AST extraction
                              ▼
               ┌──────────────────────────────┐
               │     Test Meta-Schema (IR)    │
               │  - fixtures, steps, asserts  │
               │  - allure metadata           │
               │  - pyramid layers            │
               └──────────────────────────────┘
                              │
              (2) Template-based generation
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  Java/JUnit5          TypeScript/Vitest       C#/NUnit
  + Allure             + Allure                + Allure
  + Gradle             + npm                   + dotnet
```

## Installation

Copy the `src/greedy_token/codegen/` directory into your greedy-token installation:

```bash
# From greedy-token root:
cp -r path/to/greedy-token-codegen/src/greedy_token/codegen src/greedy_token/
```

Add to `src/greedy_token/cli.py`:

```python
from greedy_token.codegen.cli import add_codegen_parser
# ... in build_parser():
add_codegen_parser(sub)
```

## Usage

### List available targets

```bash
greedy-token codegen targets
```

Available targets:
- `java-junit5-gradle` / `java-junit5-maven`
- `kotlin-junit5-gradle`
- `typescript-vitest` / `typescript-playwright`
- `csharp-nunit` / `csharp-xunit`
- `go-testing`

### Extract meta-schema from pytest tests

```bash
greedy-token codegen extract tests/ --name my-suite -o schema.json
```

### Generate test project

```bash
# From schema file:
greedy-token codegen generate --target java-junit5-gradle --schema schema.json -o ./generated

# Directly from tests:
greedy-token codegen generate --target typescript-vitest --tests-dir tests/ -o ./generated
```

### Generate CI matrix workflow

```bash
greedy-token codegen matrix --tests-dir tests/ -o . --targets java-junit5-gradle,typescript-vitest
```

## Meta-Schema IR

The intermediate representation captures:

```python
TestSuite
├── name, version, description
├── global_fixtures: List[Fixture]
│   └── name, scope, autouse, setup/teardown hints
└── modules: List[TestModule]
    ├── name, path
    ├── allure: AllureMetadata (epic, feature, story, etc.)
    ├── fixtures: List[Fixture]
    └── tests: List[TestCase]
        ├── id, name
        ├── allure: AllureMetadata
        ├── layer: PyramidLayer (unit, component, integration, e2e)
        ├── steps: List[TestStep]
        │   ├── name, description
        │   └── assertions: List[Assertion]
        │       └── type, actual, expected
        ├── parameters: List[ParameterSet]
        └── markers, skip_reason, hypothesis_settings
```

## Why not RAG?

| Aspect | RAG + ADR | Crystallization (codegen) |
|--------|-----------|---------------------------|
| **Cost per generation** | LLM tokens | ~0 (templates) |
| **Speed** | Seconds | Milliseconds |
| **Determinism** | Varies | Same input → same output |
| **Audit** | Black box | Reviewable templates |
| **Offline** | Requires API | Fully local |

## Extending

To add a new target:

1. Add target config to `schema.py:TARGETS`
2. Add generator function in `generator.py`
3. Register in `_GENERATORS` dict

## License

MIT (same as greedy-token)
