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
- RAG-based metric retrieval
- Structured output
- Error recovery
- Result validation
- Evaluation and testing

This is not intended to become a large enterprise platform during the MVP
stage.

## 2. User Background and Constraints

The developer is a computer science master's student with experience in
Python, data processing, machine learning, and basic RAG.

Available development time is approximately 1–2 hours per day.

Prefer solutions that are:

- Simple
- Runnable
- Testable
- Easy to explain in interviews
- Appropriate for a 20-day MVP

Avoid unnecessary complexity.

## 3. MVP Workflow

The intended workflow is:

1. Receive an English natural-language question during the MVP.
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
- DuckDB for the selected Olist MVP
- Pandas
- Pydantic
- LangGraph or an explicit Python workflow
- Streamlit
- pytest
- Environment variables for secrets

Prefer an explicit Python workflow over an Agent framework when the framework
does not provide meaningful value.

Do not introduce multiple agents, microservices, Kubernetes, model fine-tuning,
or complex authentication during the MVP.

## 5.1 Language Architecture

The current MVP is English-first:

- Product input and output are English only.
- System prompts, Agent prompts, tool names, tool descriptions, and evaluation
  questions are English.
- Python filenames, modules, classes, functions, variables, tests, and
  machine-readable configuration use English.
- DuckDB table and column names preserve the original English Olist schema.
- SQL uses those original English identifiers.
- Metrics, dimensions, and semantic entities use stable English canonical
  identifiers.
- When the question interface is implemented, non-English input must return an
  explicit unsupported-language response. Do not add an implicit translation
  chain.

Preserve source-language data:

- Do not overwrite or bulk-translate Portuguese values in the Olist files.
- Preserve both `product_category_name` and the official
  `product_category_name_english` mapping when category labels are used.
- Prefer the official English label for analysis while keeping the Portuguese
  value traceable.

Chinese question answering is a later extension, not part of the current MVP.
Add it primarily through semantic aliases, prompts, and response rendering.
Chinese input must still map to English canonical identifiers and the existing
English schema. Do not create a Chinese database schema, duplicate translated
tables, change SQL tool interfaces, or introduce a full i18n framework now.

Chinese prose in repository documentation and Chinese explanations in Codex
responses are developer-facing communication; they do not imply that the
product runtime supports Chinese. Do not claim bilingual support until the
corresponding implementation and English/Chinese evaluation tests exist.

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

## 12. Documentation

Keep the following documents current:

- `README.md`
- `docs/PRODUCT_SPEC.md`
- `docs/PRODUCT_SPEC.docx` as the formatted reading copy
- `docs/DATASET.md`
- `docs/DATA_AUDIT.md`

Create `docs/ARCHITECTURE.md` and `docs/EVALUATION.md` when those implementation
phases begin. Do not present planned architecture or evaluation metrics as
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
- Treat this response-language preference as developer communication, separate
  from the MVP product's English-only input and output contract.
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
