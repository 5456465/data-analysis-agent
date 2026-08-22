# Simplified Architecture

```mermaid
flowchart TB
    entry["Business User → Streamlit<br/>Shared Agent Entry"]
    router["Router<br/>structured routing"]
    sqlonly["SQL_ONLY<br/>Text-to-SQL"]
    sqlpython["SQL_THEN_PYTHON<br/>Planner"]
    safesql["Safe SQL<br/>read-only + bounded"]
    python["Controlled Python<br/>when needed"]
    validation["Result Validation"]
    synthesis["Deterministic Synthesis<br/>source of truth"]
    answer["Evidence-bound Answer"]

    entry --> router
    router -->|SQL_ONLY| sqlonly
    router -->|SQL_THEN_PYTHON| sqlpython
    sqlonly --> safesql
    sqlpython --> safesql
    safesql -->|SQL_ONLY| validation
    safesql -->|SQL_THEN_PYTHON| python
    python --> validation
    validation --> synthesis
    synthesis --> answer

    subgraph trust["Trust / Support"]
        direction LR
        semantic["Semantic Layer<br/>Business metric semantics"]
        trace["ExecutionTrace<br/>What happened?"]
        observability["Observability<br/>Latency · tokens · LLM calls"]
    end

    semantic -. business semantics .-> sqlonly
    semantic -. business semantics .-> sqlpython

    infrastructure["DeepSeek · model services<br/>DuckDB / Olist · read-only analytics<br/>Docker / Render · public runtime"]
    safesql -. read-only data .-> infrastructure

    integration["Integration Evidence — not main execution path<br/>MCP · Native Function Calling"]
```

- Default orchestration: **Explicit Python workflow**.
- Alternative: **LangGraph over the same shared components**.

FastAPI remains a secondary developer/integration entry over the same Agent;
Public V1 uses Streamlit on Render.

The detailed engineering and deployment view remains in
[`architecture.md`](architecture.md).
