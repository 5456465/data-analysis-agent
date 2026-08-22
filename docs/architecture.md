# Architecture

The public product uses the explicit Python workflow. LangGraph is an optional
orchestration over the same business components, while MCP and Native Function
Calling remain separate integration evidence.

```mermaid
flowchart TB
    subgraph entry["1. Entry / Interfaces"]
        public["Public user<br/>Render → Docker → Streamlit"]
        api["Developer / integration client<br/>FastAPI"]
    end

    subgraph orchestration["2. Orchestration"]
        workflow["Shared Agent Entry<br/>Explicit Python Workflow — default"]
        langgraph["LangGraph<br/>alternative orchestration"]
    end

    public --> workflow
    api --> workflow

    subgraph execution["3. Analysis Execution"]
        schema["Schema Inspection"]
        router["Router<br/>structured JSON"]
        textsql["SQL_ONLY<br/>Text-to-SQL<br/>optional one-shot repair"]
        planner["SQL_THEN_PYTHON<br/>Planner"]
        safesql["Safe SQL<br/>read-only + bounded"]
        python["Controlled Python<br/>describe · correlation · growth"]
        validation["Result Validation<br/>structural + result checks"]
        synthesis["Deterministic Synthesis<br/>source of truth"]
        narrative["Optional evidence-bound<br/>natural-language answer"]
        response["Response<br/>answer + evidence + status"]

        schema --> router
        router -->|SQL_ONLY| textsql
        router -->|SQL_THEN_PYTHON| planner
        textsql --> safesql
        planner --> safesql
        safesql -->|SQL result| validation
        safesql -->|planned rows| python
        python --> validation
        validation --> synthesis
        synthesis --> narrative
        narrative --> response
        synthesis -->|deterministic fallback| response
    end

    workflow --> schema
    langgraph -. reuses shared components .-> schema

    subgraph trust["4. Trust / Cross-cutting"]
        semantic["Semantic Layer<br/>Metric Definitions + Query Constraints"]
        trace["ExecutionTrace<br/>What happened?"]
        observability["Observability<br/>latency · tokens · LLM calls · route/status"]
    end

    semantic -. business semantics .-> textsql
    semantic -. business semantics .-> planner
    response -. derived evidence .-> trace
    workflow -. request-scoped measurement .-> observability

    subgraph support["5. Data / Model / Runtime"]
        deepseek["DeepSeek<br/>routing · planning · SQL/repair · constrained NL<br/>runtime secret only"]
        duckdb["DuckDB + Olist dataset<br/>read-only analytical data"]
        artifact["GitHub Release data-v1<br/>build-time size + SHA256 verification<br/>DuckDB baked into image"]
        integration["Integration Evidence — not the main path<br/>MCP stdio: inspect_schema · run_readonly_sql · get_metric_definition<br/>Native Function Calling spike: run_readonly_sql"]
    end

    deepseek -.-> router
    deepseek -.-> textsql
    deepseek -.-> planner
    deepseek -.-> narrative
    duckdb -.-> schema
    duckdb -.-> safesql
    artifact -->|verified image input| public
    integration -. shared read-only adapters .-> safesql
```

## Reading the diagram

- The default code-level entry chain is
  `answer_question_for_user` → `answer_question_with_validation` →
  `answer_question_with_tools`. Streamlit and FastAPI both use this chain.
- The SQL-only path generates SQL and may make one repair attempt after an
  eligible execution error. Every initial or repaired query crosses the same
  read-only, row-bounded SQL executor.
- The SQL-then-Python path uses SQL to prepare bounded tabular input, then runs
  one allow-listed deterministic operation. It does not execute generated
  Python code or give Python direct database access.
- The metric catalog is injected directly into Text-to-SQL and Planner prompts.
  Router policy is currently defined by its own structured routing prompt; it
  does not directly read the metric catalog.
- Result validation checks execution structure and result consistency. The
  deterministic synthesis remains authoritative; the optional model-generated
  narrative can only present the validated evidence.
- ExecutionTrace is a deterministic account derived from the result. Separate
  request observability records stage latency and provider usage metadata.
- Public V1 is one Render-hosted Docker/Streamlit service. FastAPI is a
  developer/integration entry supported by the same image, not a second public
  Render service.
- The versioned DuckDB artifact is downloaded and checksum-verified during the
  Docker build, then included in the image. There is no runtime database
  download, and `DEEPSEEK_API_KEY` is supplied only as a runtime secret.
- MCP stdio and the Native Function Calling spike reuse the governed read-only
  adapters independently; neither replaces the production Router or workflow.
