"""Parse a SQL Server ShowPlan XML file into a normalized operator tree."""
from lxml import etree

NS = {"s": "http://schemas.microsoft.com/sqlserver/2004/07/showplan"}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _warn(w):
    detail = w.get("Expression") or w.get("ConvertIssue") or ""
    issue = w.get("ConvertIssue")
    return {"type": etree.QName(w).localname,
            "detail": f"{issue}: {detail}" if issue and issue != detail else detail}


def _node(el):
    kids = [_node(c) for c in el.xpath("./*/s:RelOp", namespaces=NS)]
    sub = _f(el.get("EstimatedTotalSubtreeCost"))
    obj = el.xpath("./*/s:Object", namespaces=NS)
    run = el.xpath("./s:RunTimeInformation/s:RunTimeCountersPerThread", namespaces=NS)
    o = obj[0] if obj else None
    return {
        "node_id": int(_f(el.get("NodeId"))),
        "physical_op": el.get("PhysicalOp", ""),
        "logical_op": el.get("LogicalOp", ""),
        "est_rows": _f(el.get("EstimateRows")),
        "actual_rows": sum(_f(r.get("ActualRows")) for r in run) if run else None,
        "actual_execs": sum(_f(r.get("ActualExecutions")) for r in run) if run else None,
        "table_rows": _f(el.get("TableCardinality")),
        "row_goal": el.get("EstimateRowsWithoutRowGoal") is not None,
        "subtree_cost": sub,
        "own_cost": max(0.0, sub - sum(k["subtree_cost"] for k in kids)),
        "object": ".".join(o.get(a) for a in ("Schema", "Table") if o is not None and o.get(a)) if o is not None else "",
        "index": o.get("Index", "") if o is not None else "",
        "warnings": [_warn(w) for w in el.xpath("./s:Warnings/*", namespaces=NS)],
        "children": kids,
    }


def _pct(n, total):
    n["cost_pct"] = round(100 * n["own_cost"] / total, 1) if total else 0.0
    for c in n["children"]:
        _pct(c, total)


def parse(xml_bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"This file is not valid XML: {e}")
    if etree.QName(root).localname != "ShowPlanXML":
        raise ValueError("This is not a SQL Server execution plan (ShowPlanXML expected).")
    stmts = root.xpath("//s:StmtSimple[s:QueryPlan/s:RelOp]", namespaces=NS)
    if not stmts:
        raise ValueError("No query plan found in this file.")
    stmt = max(stmts, key=lambda s: _f(s.get("StatementSubTreeCost")))
    qp = stmt.find("s:QueryPlan", NS)
    tree = _node(qp.find("s:RelOp", NS))
    total = tree["subtree_cost"]
    _pct(tree, total)
    missing = []
    for g in qp.xpath("./s:MissingIndexes/s:MissingIndexGroup", namespaces=NS):
        for mi in g.findall("s:MissingIndex", NS):
            cols = {cg.get("Usage"): [c.get("Name") for c in cg.findall("s:Column", NS)]
                    for cg in mi.findall("s:ColumnGroup", NS)}
            missing.append({"impact": _f(g.get("Impact")), "schema": mi.get("Schema"),
                            "table": mi.get("Table"), "columns": cols})
    return {"statement": stmt.get("StatementText", "").strip(), "total_cost": total,
            "tree": tree, "missing_indexes": missing,
            # SSMS puts plan-wide warnings (implicit conversion, spills, memory grant) here, not on an operator.
            "warnings": [_warn(w) for w in qp.xpath("./s:Warnings/*", namespaces=NS)]}
