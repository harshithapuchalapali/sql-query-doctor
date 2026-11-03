# SQL Query Doctor — Documentation

A Flask web app that reads a SQL Server execution plan, draws it as an interactive graph, flags the usual causes of a slow query with a rule engine, and optionally explains the plan in plain English using the Gemini API.

Everything in this document was checked against the code in this folder (`app.py`, `config.py`, `web/`, `core/`, `static/index.html`).

---

## 1. What problem it solves

`SET STATISTICS` and SSMS give you a raw XML plan. Reading that XML means knowing ShowPlan by heart: which operator owns the cost, whether the estimate is wrong, whether a scan is unavoidable, which index SQL Server says is missing.

This tool does four things with that file:

1. Parses the XML into an operator tree with per-operator cost shares.
2. Renders the tree as a zoomable graph so the expensive branch is obvious.
3. Runs fixed, explainable rules over it and reports findings with severity.
4. Optionally asks an LLM to translate those facts into beginner-friendly prose.

No database connection is needed. The plan file is the only input.

---

## 2. Features

| Feature | Detail |
|---|---|
| Plan input | Upload `.sqlplan` / `.xml` (max 16 MB), or click **Try a sample plan** |
| Graph | D3 tree, one node per operator, coloured by share of plan cost, edge width scales with estimated rows, scroll-zoom and drag-pan |
| Findings | Rule engine with `high` / `medium` / `low` severity, sorted worst first |
| Fix suggestions | Missing-index findings include a ready-to-run `CREATE NONCLUSTERED INDEX` with a copy button |
| Operator details | Click a node (or a finding) to see cost share, estimated vs actual rows, object, index, warnings |
| AI explanation | Optional Gemini summary, "why it is slow", fixes with SQL, and risks |
| Offline behaviour | Without `GEMINI_API_KEY` the app still works; only the explanation panel shows a hint |
| Last run restore | The last analysis is kept in `sessionStorage` and restored on reload |

---

## 3. Quick start

Windows (PowerShell / cmd):

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000> and click **Try a sample plan**.

Requirements (`requirements.txt`): `flask>=3.0`, `lxml>=5.0`. Python 3.9+ (the code uses `dict.fromkeys`, f-strings, `str.removeprefix` → 3.9 minimum).

The UI loads D3 from a CDN (`cdnjs`, d3 7.9.0), so the graph needs internet on first load. Everything else is local.

Self-check (no network, no browser):

```
python test_app.py
```

---

## 4. Configuration

Environment variables, read through `config.py`:

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | no | Enables `/api/explain`. Without it the endpoint returns `ai: null` and a hint string. |
| `GEMINI_MODEL` | no | First model tried. Default `gemini-flash-lite-latest`. |

`config.gemini_key()` / `config.gemini_model()` are the only readers. `core/explain.py` receives both as arguments, so the domain never touches the environment.

A `.env` file next to `config.py` is loaded automatically (simple `KEY=VALUE` lines, `#` comments ignored, existing env vars win). `.env` is gitignored — never commit the key.

Model fallback order for each explanation request:
`GEMINI_MODEL` (or `gemini-flash-lite-latest`) → `gemini-3.6-flash` → `gemini-flash-lite-latest`.
Each free-tier model has its own daily quota, so a used-up model is skipped instead of failing the request.

---

## 5. How it works

```
.sqlplan / .xml
      │  upload (multipart form field "plan") or sample flag
      ▼
web/routes.py  /api/analyze ──► core.plan.parse() ──► core.findings.analyze()
      │                        │                       │
      │                   operator tree          findings list
      ▼
 JSON {statement, total_cost, tree, missing_indexes, warnings, findings}
      ▼
static/index.html  (graph + findings + operator details)

web/routes.py  /api/explain ──► parse() ──► analyze() ──► core.explain.explain(plan, findings, key, model) ──► Gemini REST
                                                        │
                                                 JSON explanation
```

The UI calls `/api/analyze` first (instant, deterministic) and `/api/explain` right after (slower, may fail), so a dead API key never blocks the plan view.

---

## 6. Project structure

```
sql-query-doctor/
├── app.py                 Entrypoint: create_app().run()
├── config.py              Settings and .env loading
├── web/__init__.py        App factory, 413 handler
├── web/routes.py          Flask routes, upload handling
├── core/plan.py           ShowPlan XML → operator tree + missing indexes + warnings
├── core/findings.py       Rule engine → findings (no AI)
├── core/explain.py        Optional Gemini explanation (REST, no SDK, with cache)
├── static/index.html      Whole frontend: CSS, markup, D3 graph, fetch calls
├── sample_plans/slow_query.sqlplan   Demo plan behind "Try a sample plan"
├── test_app.py            Offline self-check of the API and its trust boundary
├── requirements.txt
└── README.md
```

### Layers and the dependency rule

```
app.py ──► web/ ──► core/
             └────► config.py
```

| Layer | Holds | May import |
|---|---|---|
| `core/` | parsing, rule engine, AI prompting/caching | `core/`, stdlib |
| `web/` | HTTP only: read request, call core, `jsonify`, 413 handler | `web/`, `core/`, `config`, Flask |
| `config.py` | paths, upload limit, env access | stdlib |
| `app.py` | composition root | `web/` |

`core/` never imports Flask, `config`, or `web`, and never reads `os.environ` — everything it needs arrives as a function argument. That is what keeps it testable and framework-independent. Test with:

```
grep -ri flask core/     # must print nothing
```

---

## 7. API reference

All endpoints return JSON. Errors are `{"error": "<message>"}`.

### `GET /`
Serves `static/index.html`.

### `GET /api/health`
```json
{"status": "ok"}
```

### `POST /api/analyze`
Body: `multipart/form-data`, either
- `plan=<file>` — the uploaded `.sqlplan` / `.xml`, or
- `sample=1` — analyse `sample_plans/slow_query.sqlplan`.

Success `200`:
```json
{
  "statement": "SELECT d.SalesOrderID, ...",
  "total_cost": 12.5,
  "tree": { "...": "operator node, see below" },
  "missing_indexes": [
    {
      "impact": 87.3,
      "schema": "[Sales]",
      "table": "[SalesOrderDetail]",
      "columns": {
        "EQUALITY": ["[ProductID]"],
        "INEQUALITY": [],
        "INCLUDE": ["[OrderQty]", "[UnitPrice]"]
      }
    }
  ],
  "warnings": [{ "type": "PlanAffectingConvert", "detail": "..." }],
  "findings": [
    {
      "rule": "missing_index",
      "severity": "high",
      "node_id": 1,
      "title": "Missing index on [Sales].[SalesOrderDetail]",
      "detail": "SQL Server estimates this index would improve the query by about 87%. ...",
      "fix_sql": "CREATE NONCLUSTERED INDEX [...] ON [Sales].[SalesOrderDetail] ([ProductID]) INCLUDE (...);"
    }
  ]
}
```

Operator node (`tree` and every `children[]` entry):

| Field | Meaning |
|---|---|
| `node_id` | `NodeId` from the plan; used to link a finding to a graph node |
| `physical_op` / `logical_op` | e.g. `Clustered Index Scan`, `Key Lookup (Clustered)` |
| `est_rows` | `EstimateRows` |
| `actual_rows` / `actual_execs` | summed over runtime counters, `null` for estimated-only plans |
| `table_rows` | `TableCardinality` |
| `row_goal` | `true` when `EstimateRowsWithoutRowGoal` is present |
| `subtree_cost` / `own_cost` | `EstimatedTotalSubtreeCost`, and that minus children |
| `cost_pct` | `own_cost` as a percentage of the whole plan |
| `object` / `index` | `Schema.Table` and index name when the operator touches one |
| `warnings` | operator-level warnings |
| `children` | child operators |

Errors:
| Status | When |
|---|---|
| `400` | no file, invalid XML, not `ShowPlanXML`, no query plan inside (all raised as `PlanError`) |
| `413` | body larger than 16 MB (`MAX_CONTENT_LENGTH`) |

### `POST /api/explain`
Body: `application/json` with the two fields `/api/analyze` returned, so the plan is not parsed twice:

```json
{"plan": { "...": "everything except findings" }, "findings": [ { "...": "..." } ]}
```

Missing or wrong-typed `plan` / `findings` → `400`. Malformed tree or findings → `400` with
`"The analysis data was not usable. Upload the plan again."` Otherwise always `200`.

```json
{
  "ai": {
    "summary": "This plan scans the whole order-detail table ...",
    "why_slow": ["The clustered index scan reads ~121k rows to return 500"],
    "fixes": [{ "title": "Add the missing index", "explanation": "...", "sql": "CREATE ..." }],
    "risks": ["Every index slows down writes"]
  },
  "ai_status": "ok"
}
```

When the AI cannot run, `ai` is `null` and `ai_status` explains why, e.g.
`"Set GEMINI_API_KEY to turn on AI explanations. Rule-based findings are shown below."`

---

## 8. Rule engine reference (`core/findings.py`)

Findings are sorted `high` → `medium` → `low`. Every rule is a fixed check — no AI involved.

| Rule | Trigger | Severity | Suggested action |
|---|---|---|---|
| `large_scan` | `Table Scan`, `Clustered Index Scan` or `Index Scan` over `max(est_rows, table_rows) >= 10,000`, and no row goal | `high` if the operator is ≥30% of plan cost, else `medium` | Selective index or tighter filter |
| `key_lookup` | `Key Lookup` / `RID Lookup` executed ≥1,000 times (actual executions, else estimate) | `medium` | Add the looked-up columns as `INCLUDE` on the driving index |
| `PlanAffectingConvert` | warning present | `high` | Match parameter type to column type (implicit conversion) |
| `SpillToTempDb` | warning present | `high` | Check row estimates, update statistics |
| `NoJoinPredicate` | warning present | `high` | A join without a predicate produces a cross product |
| `ColumnsWithNoStatistics` | warning present | `medium` | Create/refresh statistics |
| `bad_estimate` | actual rows ≥1,000 and actual/estimated ratio ≥10 or ≤0.1 | `medium` | Update statistics |
| `costly_sort` | `Sort` operator taking ≥20% of plan cost | `medium` | Index that returns rows already ordered |
| `big_nested_loop` | `Nested Loops` whose first child estimates ≥10,000 rows | `medium` | Hash or merge join may be faster |
| `missing_index` | `MissingIndexGroup` in the plan | `high` if `Impact >= 50`, else `medium` | Generated `CREATE NONCLUSTERED INDEX` (key columns + `INCLUDE`) |

Notes:
- The `row_goal` exemption exists because SQL Server sometimes scans deliberately to honour a `TOP` row goal; flagging that as a missing index would be wrong.
- Plan-wide warnings (implicit conversion, spills, memory grant) live on `QueryPlan/Warnings`, not on an operator. `_node_for()` maps such a warning to the first operator touching the named table, so the finding still highlights something in the graph.
- Missing-index findings carry `fix_sql`; all other findings carry `null`. The UI only renders a copy button when SQL exists.

---

## 9. Parsing details (`core/plan.py`)

- Namespace: `http://schemas.microsoft.com/sqlserver/2004/07/showplan`, prefix `s`.
- XML is parsed with `resolve_entities=False, no_network=True`, so a malicious plan cannot pull external entities or make network calls.
- A file is accepted only if its root element is `ShowPlanXML`; otherwise `PlanError` → `400`. `PlanError` subclasses `ValueError`, so it is also the error type for malformed XML and for plans with no `QueryPlan`.
- If a file holds several statements, the most expensive one (`StatementSubTreeCost`) is analysed.
- `own_cost = subtree_cost − Σ children subtree_cost`, floored at 0. Percentages are computed against the root's subtree cost, so they always sum to ~100%.
- Missing indexes are read from `QueryPlan/MissingIndexes/MissingIndexGroup`, keeping `Impact`, schema, table and the `EQUALITY` / `INEQUALITY` / `INCLUDE` column groups.

---

## 10. AI layer (`core/explain.py`)

- Raw REST via `urllib`, no SDK dependency.
- `explain(plan, findings, key, model)` is pure with respect to its inputs: the caller supplies the key and model, so the module reads no environment variables and can be exercised with `key=None`.
- System prompt forces JSON output and forbids inventing table or column names.
- The request payload contains only: the first 1,500 characters of the query text, the 5 most expensive operators (op, object, cost %, estimated/actual rows) and the rule findings. No plan XML, no connection info.
- Prompt hash (SHA-256) is used as an in-process cache key, so re-analysing the same plan costs nothing. The cache is a plain dict — it is lost on restart, not shared between processes, and unbounded (marked `shortcut:` in the code).
- Retries: up to 3 attempts on `429`/`5xx` with 2 s and 4 s backoff; other HTTP errors fail immediately.
- Timeout: 60 s per request.
- Failures never break the page; they surface as `ai_status`.

---

## 11. Using the UI

1. Drop a file on the page or use the file picker (`.sqlplan`, `.xml`), or click **Try a sample plan**.
2. **Query** card shows the statement text and its length.
3. **Plan** card draws the operator tree. Node colour follows cost share (red ≥30%, amber 10–30%, green <10%). Edge width grows with estimated rows. Scroll to zoom, drag to pan.
4. Click any node for **Operator details**: cost share, estimated rows, table rows, object/index, warnings.
5. **Findings** list shows severity pills and counts. Click a finding to select its operator in the graph. SQL fixes have a **Copy** button.
6. **Explanation** streams in after the analysis; if the API key is missing or the quota is gone, the panel says so and the rest of the page is unaffected.
7. **Go home** clears the view. The previous run is restored from `sessionStorage` on reload.

Findings and finding cards are keyboard reachable (`Enter` selects the operator).

---

## 12. Worked example (verified)

Input: **Try a sample plan** → `sample_plans/slow_query.sqlplan`

```
SELECT d.SalesOrderID, d.OrderQty, d.UnitPrice
FROM Sales.SalesOrderDetail d
WHERE d.ProductID = 870
```

Result: `total_cost = 12.5`, six findings.

| Severity | Rule | Operator | Meaning |
|---|---|---|---|
| high | `large_scan` | node 1, Clustered Index Scan on `[Sales].[SalesOrderDetail]` | Reads a ~121k-row table for 500 rows |
| high | `PlanAffectingConvert` | node 1 | Implicit conversion blocks an index seek |
| high | `missing_index` | node 1 | `Impact = 87.3` → SQL Server estimates ~87% less work with the generated index |
| medium | `big_nested_loop` | node 0 | Nested loops over a 121k-row outer input |
| medium | `key_lookup` | node 2, Key Lookup on `[Sales].[SalesOrderHeader]` | Repeated per row |
| medium | `bad_estimate` | node 2 | Estimate far from actual rows |

Generated fix:

```sql
CREATE NONCLUSTERED INDEX [IX_SalesOrderDetail_ProductID]
  ON [Sales].[SalesOrderDetail] ([ProductID])
  INCLUDE ([OrderQty], [UnitPrice]);
```

The 87% figure is SQL Server's own `MissingIndexGroup/@Impact` estimate stored in the plan — it is a cost estimate, not a measured wall-clock speedup. Measure before and after with `SET STATISTICS TIME ON`.

---

## 13. Security and limits

- Uploads are capped at 16 MB (`MAX_CONTENT_LENGTH`) and rejected with a JSON `413`.
- The file is never written to disk and never executed; it is parsed in memory.
- XML parsing disables entities and network access (XXE-safe).
- Error messages never echo file contents.
- No authentication: the app is meant for local use. Do not expose it publicly without adding auth and a request limit.
- `debug=True` is set in the `__main__` block — turn it off before any deployment.

---

## 14. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `This is not a SQL Server execution plan (ShowPlanXML expected).` | The file is a saved query, a `.sql` script, or a plan from another engine (PostgreSQL `EXPLAIN`, MySQL, Oracle). |
| `No query plan found in this file.` | A plan file with no `QueryPlan` (e.g. an estimated plan for a DDL statement). |
| `This file is not valid XML: ...` | Truncated or corrupted download. Re-save from SSMS. |
| `That request is larger than 16 MB.` | Huge plans; analyse a single statement instead of a whole batch. |
| Graph area is blank | D3 CDN blocked/offline. Findings still work. |
| "Set GEMINI_API_KEY to turn on AI explanations." | No key in `.env` or the environment. |
| "The AI is unavailable right now (HTTP 429 ...)" | Free-tier daily quota used up; the fallback models were used up too. Try tomorrow or raise the quota. |
| `actual_rows` is `null` everywhere | The plan is estimated-only. Save it with **Include Actual Execution Plan** for real row counts, otherwise `bad_estimate` and actual-execution checks cannot fire. |

---

## 15. Known limitations

- SQL Server only (ShowPlan). Azure SQL Database plans normally parse; PostgreSQL/MySQL are out of scope.
- Only the most expensive statement in a multi-statement plan is analysed.
- Missing-index `Impact` is SQL Server's estimate; it is not a measured runtime improvement.
- The AI cache is in-memory per process, not persisted.
- Rules are thresholds, not a cost model: a `medium` finding can still be the real bottleneck.
- No benchmark mode and no deployment config (see README "Not included yet").
- The sample plan is synthetic, so its numbers demonstrate the UI, not a real workload.

---

## 16. Extending it

- **New rule:** add a check inside `analyze()` in `core/findings.py` using the `add(severity, node_id, rule, title, detail, fix_sql)` helper. Keep the detail factual — the AI prompt is built from these strings, and the system prompt forbids inventing facts.
- **New operator field:** add it to `_node()` in `core/plan.py`; the UI reads `d.tree` generically, so new fields only need rendering if you want them visible.
- **New endpoint:** add it to `web/routes.py`, keep the pattern `parse → analyze → jsonify`, return `400` with `{"error": ...}` for bad input, and do not import `web`/`config` from `core`.
- **Tests:** `python test_app.py` posts the sample plan to `/api/analyze` and asserts the `/api/explain` trust boundary rejects malformed bodies. Extend it there; it runs offline with no key and no browser.
