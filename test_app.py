"""Offline self-check for the /api/explain trust boundary. Run: python test_app.py"""
import io
import os

from app import app

client = app.test_client()
r = client.post("/api/analyze", data={"sample": "1"}, content_type="multipart/form-data")
assert r.status_code == 200, r.data
analysis = r.get_json()
plan = {k: v for k, v in analysis.items() if k != "findings"}

# A request with no file is a clean 400, not a 500.
assert client.post("/api/analyze", data={}, content_type="multipart/form-data").status_code == 400

# Bad bodies are rejected instead of crashing the route.
assert client.post("/api/explain", data="nope").status_code == 400
assert client.post("/api/explain", json={"plan": "x", "findings": []}).status_code == 400
os.environ["GEMINI_API_KEY"] = "dummy"  # lets explain() reach the plan data, no network call
assert client.post("/api/explain", json={"plan": {}, "findings": []}).status_code == 400
os.environ.pop("GEMINI_API_KEY", None)

# The real analysis is accepted; with no key the explanation is skipped, not an error.
r = client.post("/api/explain", json={"plan": plan, "findings": analysis["findings"]})
assert r.status_code == 200, r.data
assert isinstance(r.get_json()["ai_status"], str), r.data

# Regression: a plan deeper than lxml's 256-level default parses instead of being called invalid XML.
NS = "http://schemas.microsoft.com/sqlserver/2004/07/showplan"
chain = "".join(
    f'<RelOp NodeId="{i}" PhysicalOp="Nested Loops" LogicalOp="Inner Join" EstimateRows="1" '
    f'EstimatedTotalSubtreeCost="{200 - i}"><NestedLoops>' for i in range(1, 201))
deep = (f'<ShowPlanXML xmlns="{NS}"><BatchSequence><Batch><Statements><StmtSimple StatementText="s" '
        f'StatementSubTreeCost="200"><QueryPlan>{chain}' + "</NestedLoops></RelOp>" * 200 +
        "</QueryPlan></StmtSimple></Statements></Batch></BatchSequence></ShowPlanXML>").encode()
r = client.post("/api/analyze", data={"plan": (io.BytesIO(deep), "deep.sqlplan")},
                content_type="multipart/form-data")
assert r.status_code == 200, r.data
levels, stack = 0, [(r.get_json()["tree"], 1)]
while stack:
    node, level = stack.pop()
    levels = max(levels, level)
    stack += [(k, level + 1) for k in node["children"]]
assert levels == 200, levels

# Regression: a missing-index suggestion without a Table attribute must not 500 the rule engine.
no_table = (f'<ShowPlanXML xmlns="{NS}"><BatchSequence><Batch><Statements><StmtSimple StatementText="s" '
            f'StatementSubTreeCost="1"><QueryPlan><RelOp NodeId="1" PhysicalOp="Table Scan" LogicalOp="Scan" '
            f'EstimateRows="100" EstimatedTotalSubtreeCost="1"/><MissingIndexes><MissingIndexGroup Impact="90">'
            f'<MissingIndex><ColumnGroup Usage="EQUALITY"><Column Name="[a]"/></ColumnGroup></MissingIndex>'
            f'</MissingIndexGroup></MissingIndexes></QueryPlan></StmtSimple></Statements></Batch>'
            f'</BatchSequence></ShowPlanXML>').encode()
r = client.post("/api/analyze", data={"plan": (io.BytesIO(no_table), "x.sqlplan")},
                content_type="multipart/form-data")
assert r.status_code == 200, r.data
assert r.get_json()["findings"][0]["fix_sql"] is None, r.data

print("ok")
