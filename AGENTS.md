# AGENTS.md

## 1. Project Overview

Project name: Data Analysis Agent

Chinese name: 可验证的多工具数据分析 Agent

This project is a portfolio project for AI Agent and LLM application
development internships.

The system accepts natural-language data analysis questions and uses
controlled tools to inspect database schemas, retrieve metric definitions,
execute read-only SQL, perform Python analysis, generate charts, validate
results, and return traceable conclusions.

The primary goal is to demonstrate:

- Python engineering
- LLM API integration
- Tool calling
- Agent workflow orchestration
- Business metric retrieval
- Structured output
- Error recovery
- Result validation
- Evaluation and testing

This remains a portfolio-scale project and is not intended to become a large
enterprise platform.

## 2. User Background and Constraints

The developer is a computer science master's student with experience in
Python, data processing, machine learning, and basic RAG.

Available development time is approximately 1–2 hours per day.

Prefer solutions that are:

- Simple
- Runnable
- Testable
- Easy to explain in interviews
- Appropriate for the current late-stage portfolio scope

Avoid unnecessary complexity.

## 3. Current Workflow

The intended workflow is:

1. Receive a Chinese or English natural-language question through a supported
   product interface.
2. Retrieve the relevant business metric definition when needed.
3. Inspect the database schema.
4. Decide whether to use SQL, Python analysis, or chart generation.
5. Execute tools in a controlled environment.
6. Validate the result.
7. Retry or repair recoverable errors.
8. Return the conclusion, SQL, data range, evidence, and validation status.

## 4. Planned Tools

The system may expose the following tools:

- `inspect_schema`
- `search_metric_definition`
- `run_readonly_sql`
- `run_python_analysis`
- `generate_chart`
- `validate_result`

Do not implement all tools at once. Implement and test them incrementally.

## 5. Preferred Technology Stack

Unless there is a clear technical reason to change:

- Python 3.11+
- DuckDB for the selected Olist project
- Pandas
- Pydantic
- LangGraph or an explicit Python workflow
- Streamlit
- pytest
- Environment variables for secrets

Prefer an explicit Python workflow over an Agent framework when the framework
does not provide meaningful value.

Do not introduce multiple agents, microservices, Kubernetes, model fine-tuning,
or complex authentication in the current project scope.

## 5.1 Language Architecture

The current product supports Chinese questions and `zh-CN` answers while
preserving English internal technical contracts:

- Streamlit is a Chinese business-user interface.
- FastAPI accepts Chinese questions and passes them unchanged into the existing
  Agent workflow.
- Product-level services support Chinese question input and `zh-CN` answer
  rendering; English input and answer rendering remain supported.
- System prompts, Agent prompts, tool names, tool descriptions, and evaluation
  questions use English unless an implemented product behavior requires
  otherwise.
- Python filenames, modules, classes, functions, variables, tests, and
  machine-readable configuration use English.
- DuckDB table and column names preserve the original English Olist schema.
- SQL uses those original English identifiers.
- Routes, statuses, stages, tool operations, metrics, dimensions, and semantic
  entities use stable English canonical identifiers.

Preserve source-language data:

- Do not overwrite or bulk-translate Portuguese values in the Olist files.
- Preserve both `product_category_name` and the official
  `product_category_name_english` mapping when category labels are used.
- Prefer the official English label for analysis while keeping the Portuguese
  value traceable.

Chinese support is implemented through semantic aliases, prompts, and response
rendering. Chinese input must continue to map to English canonical identifiers
and the existing English schema. Do not create a Chinese database schema,
duplicate translated tables, localize machine contracts, change SQL tool
interfaces, or introduce a full i18n framework.

Chinese prose in repository documentation and Chinese explanations in Codex
responses remain developer-facing communication. User-facing Chinese support
does not imply that internal technical identifiers or machine-readable
contracts should be translated.

## 6. Development Rules

Before implementing a module, define:

- Responsibility
- Inputs
- Outputs
- Data structures
- Failure cases
- Acceptance criteria

Make small, reviewable changes.

Do not generate the entire project in one step.

For every coding task:

1. Inspect the existing repository first.
2. Explain the proposed change briefly.
3. List the files that will be changed.
4. Implement the smallest complete solution.
5. Add or update tests.
6. Run the relevant tests.
7. Report what was completed and what remains.

Do not claim that a feature is complete unless its implementation and tests
exist in the repository.

Implementation source-of-truth rules:

- Exact implementation behavior is defined by source code and tests.
- Tests are the executable contract for deterministic module behavior.
- Function-level implementation details do not need to be duplicated in
  `docs/PRODUCT_SPEC.md`.
- Documentation should describe stable design intent, not mirror every code
  change.
- Details such as the exact `run_readonly_sql` fetch strategy, error codes, and
  internal helpers belong in source code and tests unless they materially
  change a documented product requirement.

Do not run `git commit`, `git push`, `git reset`, or `git clean` unless the
developer explicitly requests it.

## 7. Code Quality

All Python code should:

- Use clear module boundaries
- Include appropriate type annotations
- Use descriptive names
- Avoid unnecessary abstraction
- Handle expected exceptions
- Avoid silently swallowing errors
- Keep functions focused
- Include docstrings when behavior is not obvious
- Follow the existing project style

Do not invent APIs, classes, packages, or framework functions.

When using rapidly changing libraries, check the installed version or official
documentation before writing version-sensitive code.

## 8. Security Requirements

The database execution layer must be read-only.

Reject or block statements such as:

- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- CREATE
- ATTACH
- PRAGMA writes

Consider:

- Query timeout
- Row limits
- Tool-call limits
- Maximum retry count
- API-key protection
- Sensitive log redaction
- Prompt-injection risks
- Unsafe generated Python code

Do not use company code, company data, internal documents, or company devices'
private files.

Use public datasets with clearly documented sources and licenses.

## 9. Reliability Requirements

Handle at least the following cases:

- Invalid SQL
- Missing table or column
- Empty query result
- Incorrect data type
- Model output parsing failure
- Tool execution failure
- Timeout
- Unsupported request
- Insufficient data
- Ambiguous metric definition

Never fabricate a data conclusion when the available evidence is insufficient.

Where possible, every answer should expose:

- SQL used
- Tables and fields used
- Data range
- Metric definition
- Validation status
- Uncertainty or limitations

## 10. Evaluation

Evaluation is part of the product, not an optional final feature.

The project should eventually evaluate:

- SQL execution success rate
- Numerical answer accuracy
- Tool-selection accuracy
- SQL repair success rate
- Metric-definition accuracy
- Chart-type suitability
- Average latency
- Model usage or cost
- Typical failure cases

Metrics must have explicit definitions and reproducible calculations.

## 11. Testing

Use `pytest`.

For each module, cover:

- Normal cases
- Boundary cases
- Expected failures
- Security-sensitive cases

Tests must not depend on private credentials or irreversible external actions.

After modifying code, run the smallest relevant test set. Before considering a
milestone complete, run the full test suite.

### Windows Codex pytest rule

On Windows, when Codex runs pytest inside its sandbox, do not use the default
pytest temporary directory or pytest cache. Codex must use:

```text
python -m pytest --basetemp="%USERPROFILE%\codex-pytest-temp" -p no:cacheprovider
```

For targeted tests, keep the same flags, for example:

```text
python -m pytest tests/test_example.py --basetemp="%USERPROFILE%\codex-pytest-temp" -p no:cacheprovider
```

This workaround applies only when Codex itself runs pytest on Windows. Do not
change the `pyproject.toml` pytest defaults, application code, or test code to
work around this Codex Windows sandbox ACL issue. Do not treat the workaround
command as the canonical developer command. In a normal developer shell, the
canonical test command remains:

```text
python -m pytest
```

## 12. Documentation

Use the following maintenance rules instead of updating every document after
each small feature:

### README

Update `README.md` only at a milestone or when the current feature status,
installation, usage, or other reader-facing behavior changes materially.

### Product specification

Update `docs/PRODUCT_SPEC.md` only when one or more of the following changes:

- Product scope
- MVP requirements
- Non-goals
- Acceptance criteria
- Important product-level design decisions

Do not automatically update `docs/PRODUCT_SPEC.md` for an ordinary function
addition, internal implementation change, test-count change, or Prompt tuning.

`docs/PRODUCT_SPEC.docx` is a formatted reading copy, not the continuously
synchronized source of truth. Synchronize or export it from the Markdown
version only when the developer explicitly requests it or at an important
milestone. A normal coding task must not automatically modify or regenerate the
DOCX file.

### Dataset documentation

Update `docs/DATASET.md` or `docs/DATA_AUDIT.md` only when the data source, data
version, audited facts, or documented data limitations change.

### Additional documentation

Create a separate architecture or evaluation document only when the developer
explicitly requests it or when demonstrated project complexity requires one.
Do not create new documentation automatically because a development phase has
started.

For a normal small coding task:

1. Change the implementation.
2. Update or add tests.
3. Run the relevant validation.
4. Do not update the PRD, DOCX, or other documentation unless the task
   materially changes documented behavior or the developer explicitly requests
   a documentation update.

When documentation is updated, maintain the relevant document rather than all
documents by default. The repository may contain:

- `README.md`
- `docs/PRODUCT_SPEC.md`
- `docs/PRODUCT_SPEC.docx`
- `docs/DATASET.md`
- `docs/DATA_AUDIT.md`

Do not present planned architecture, features, or evaluation metrics as
implemented before corresponding code and tests exist.

Current dataset facts that all documentation and code must preserve:

- Olist Brazilian E-Commerce is the only selected dataset.
- Raw files live under `data/raw/` and are verified by
  `docs/olist_raw.sha256`.
- The data mainly covers 2016–2018.
- There is no complete refund table or product-cost field.
- `order_items` and `order_payments` must be aggregated separately to
  `order_id` grain before joining monetary values.

The README should contain:

- Problem statement
- Architecture
- Feature status
- Installation steps
- Running instructions
- Test commands
- Demo examples
- Dataset source and license
- Known limitations

Clearly distinguish:

- Implemented
- In progress
- Planned
- Optional

## 13. Response Style

When assisting the developer:

- Use Chinese for explanations unless asked otherwise.
- Keep code identifiers and technical terms in English where appropriate.
- Treat this response-language preference as developer communication; product
  language behavior remains defined by the implemented interfaces and tests.
- Be direct and critical.
- Point out overengineering and unrealistic scope.
- Prefer one recommended solution over a long list of alternatives.
- Do not use marketing language.
- Do not exaggerate the project's novelty or completion level.

When a task is too large, split it into the smallest independently testable
step.

At the end of a coding task, report:

1. Completed work
2. Changed files
3. Commands run
4. Test results
5. Known limitations
6. One recommended next task
