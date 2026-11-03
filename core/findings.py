"""Rule engine: turns the parsed plan into factual findings (no AI involved)."""
from core.plan import walk

SCANS = {"Table Scan", "Clustered Index Scan", "Index Scan"}
WARNINGS = {
    "PlanAffectingConvert": ("high", "Implicit conversion",
        "A data type mismatch forces SQL Server to convert values, which can block index seeks and distort row estimates. Match the parameter type to the column type."),
    "SpillToTempDb": ("high", "Spill to TempDB",
        "An operator ran out of memory and wrote to disk. Check row estimates and update statistics."),
    "ColumnsWithNoStatistics": ("medium", "Missing statistics",
        "No statistics exist for some columns, so row estimates may be wrong."),
    "NoJoinPredicate": ("high", "Join without predicate",
        "A join has no join condition, which can produce a huge cross product."),
}
ORDER = {"high": 0, "medium": 1, "low": 2}


def _index_sql(m):
    keys = (m["columns"].get("EQUALITY") or []) + (m["columns"].get("INEQUALITY") or [])
    inc = m["columns"].get("INCLUDE") or []
    if not keys:
        return None
    name = "IX_" + m["table"].strip("[]") + "_" + "_".join(c.strip("[]") for c in keys)
    sql = f"CREATE NONCLUSTERED INDEX [{name}]\n  ON {m['schema']}.{m['table']} ({', '.join(keys)})"
    return sql + (f"\n  INCLUDE ({', '.join(inc)});" if inc else ";")


def _node_for(plan, text):
    """Operator that touches the table named in text, so a finding can select it in the plan graph."""
    for n in walk(plan["tree"]):
        table = n["object"].split(".")[-1].strip("[]")
        if table and f"[{table}]" in text:
            return n["node_id"]
    return plan["tree"]["node_id"]


def analyze(plan):
    out = []

    def add(sev, node_id, rule, title, detail, fix=None):
        out.append({"rule": rule, "severity": sev, "node_id": node_id,
                    "title": title, "detail": detail, "fix_sql": fix})

    def warning(w, node_id):
        if w["type"] in WARNINGS:
            sev, title, detail = WARNINGS[w["type"]]
            add(sev, node_id, w["type"], title, detail + (f" ({w['detail']})" if w["detail"] else ""))

    for n in walk(plan["tree"]):
        op, pct, rows, nid = n["physical_op"], n["cost_pct"], n["est_rows"], n["node_id"]
        where = n["object"] or op
        big = max(rows, n["table_rows"])
        if op in SCANS and big >= 10000 and not n["row_goal"]:
            add("high" if pct >= 30 else "medium", nid, "large_scan", f"{op} on {where}",
                f"Scans a table of about {big:,.0f} rows and accounts for {pct}% of the plan cost. "
                "A selective index or a tighter filter may avoid reading the whole table.")
        execs = n["actual_execs"] if n["actual_execs"] is not None else rows
        if ("Key Lookup" in op or "RID Lookup" in op) and execs >= 1000:
            add("medium", nid, "key_lookup", f"{op} on {where}",
                f"Runs about {execs:,.0f} times, once per row found by an index. "
                "Adding the looked-up columns as INCLUDE columns in that index removes the lookup.")
        for w in n["warnings"]:
            warning(w, nid)
        if n["actual_rows"] is not None and n["actual_rows"] >= 1000:
            ratio = (n["actual_rows"] + 1) / (rows + 1)
            if ratio >= 10 or ratio <= 0.1:
                add("medium", nid, "bad_estimate", f"Row estimate is far off on {op}",
                    f"Estimated {rows:,.0f} rows but {n['actual_rows']:,.0f} were returned. "
                    "Updating statistics often fixes this and leads to better plans.")
        if op == "Sort" and pct >= 20:
            add("medium", nid, "costly_sort", "Expensive sort",
                f"Sorting takes {pct}% of the plan cost. An index that returns rows already ordered can remove it.")
        if op == "Nested Loops" and n["children"] and n["children"][0]["est_rows"] >= 10000:
            add("medium", nid, "big_nested_loop", "Nested loop over a large input",
                "Nested loops repeat work for every outer row. With a large outer input, a hash or merge join may be faster.")
    for w in plan.get("warnings", []):
        warning(w, _node_for(plan, w["detail"]))
    for m in plan["missing_indexes"]:
        sql = _index_sql(m)
        add("high" if m["impact"] >= 50 else "medium", _node_for(plan, m["table"]), "missing_index",
            f"Missing index on {m['schema']}.{m['table']}",
            f"SQL Server estimates this index would improve the query by about {m['impact']:.0f}%. "
            "Test it before creating it, since every index slows down writes.", sql)
    out.sort(key=lambda f: ORDER[f["severity"]])
    return out
