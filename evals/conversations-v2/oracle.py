"""Independent aggregate and inactivity checks for captured evidence; no production compiler."""

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path

from google.cloud import bigquery

from retail_agent.config import Settings

FROM = "FROM `bigquery-public-data.thelook_ecommerce.order_items` i JOIN `bigquery-public-data.thelook_ecommerce.products` p ON p.id=i.product_id"


def sql_parts(request, user):
    brands = request["brands"] or (
        [] if user == "ceo" else ["Levi's" if user == "bob" else "Calvin Klein"]
    )
    params = [bigquery.ArrayQueryParameter("brands", "STRING", brands)]
    where = ["(@all_brands OR p.brand IN UNNEST(@brands))"]
    params.append(bigquery.ScalarQueryParameter("all_brands", "BOOL", not brands and user == "ceo"))
    order_status = (
        "o.status='Complete'"
        if request["completed_only"]
        else "o.status NOT IN ('Cancelled','Returned')"
    )
    where.append(
        "i.status='Complete'"
        if request["completed_only"]
        else "i.status NOT IN ('Cancelled','Returned')"
    )
    where.append(
        f"EXISTS (SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders` o WHERE o.order_id=i.order_id AND o.user_id=i.user_id AND {order_status})"
    )
    if request["product_ids"]:
        where.append("i.product_id IN UNNEST(@products)")
        params.append(bigquery.ArrayQueryParameter("products", "INT64", request["product_ids"]))
    if request["customer_id"]:
        where.append("i.user_id=@customer")
        params.append(bigquery.ScalarQueryParameter("customer", "INT64", request["customer_id"]))
    return " AND ".join(where), params


def query(client, sql, params):
    dry = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=params, dry_run=True, use_query_cache=False
        ),
    )
    assert dry.total_bytes_processed <= 100_000_000
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=params, maximum_bytes_billed=100_000_000
        ),
    )
    return [dict(row) for row in job.result(timeout=60)]


def oracle(client, request, user):
    where, params = sql_parts(request, user)
    if request["kind"] == "churn":
        assert request["dimension"] == "total"
        rows = []
        for boundary in (request["start"], request["end"]):
            cutoff = date.fromisoformat(boundary) - timedelta(days=request["inactivity_days"])
            snapshot_params = [
                *params,
                bigquery.ScalarQueryParameter("snapshot", "DATE", date.fromisoformat(boundary)),
                bigquery.ScalarQueryParameter("cutoff", "DATE", cutoff),
            ]
            sql = f"""WITH eligible AS (
                SELECT DISTINCT i.user_id {FROM} WHERE {where} AND DATE(i.created_at)<@cutoff
            ), recent AS (
                SELECT DISTINCT i.user_id {FROM} WHERE {where}
                AND DATE(i.created_at)>=@cutoff AND DATE(i.created_at)<@snapshot
            )
            SELECT CAST(@snapshot AS STRING) period, 'all' cohort,
              COUNT(*) eligible_customers, COUNTIF(r.user_id IS NULL) inactive_customers,
              SAFE_DIVIDE(COUNTIF(r.user_id IS NULL),COUNT(*)) inactivity_share
            FROM eligible e LEFT JOIN recent r ON r.user_id=e.user_id
            HAVING COUNT(*)>0"""
            rows.extend(query(client, sql, snapshot_params))
        return rows
    fields = {
        "total": ("'all' AS label", [], []),
        "product": (
            "i.product_id AS product_id, p.name AS product_name",
            ["product_id", "product_name"],
            ["product_id", "product_name"],
        ),
        "customer": ("i.user_id AS user_id", ["user_id"], ["user_id"]),
        "month": ("FORMAT_TIMESTAMP('%Y-%m',i.created_at) AS month", ["month"], ["month"]),
        "category": ("p.category AS category", ["category"], ["category"]),
        "brand": ("p.brand AS brand", ["brand"], ["brand"]),
        "state": ("u.state AS state", ["state"], ["state"]),
    }
    select, groups, keys = fields[request["dimension"]]
    source = FROM + (
        " JOIN `bigquery-public-data.thelook_ecommerce.users` u ON u.id=i.user_id"
        if request["dimension"] == "state"
        else ""
    )
    params += [
        bigquery.ScalarQueryParameter("start", "DATE", date.fromisoformat(request["start"])),
        bigquery.ScalarQueryParameter("end", "DATE", date.fromisoformat(request["end"])),
        bigquery.ScalarQueryParameter(
            "limit", "INT64", max(request["limit"], len(request["product_ids"]))
        ),
    ]
    rank = request["rank_by"]
    assert rank in ("revenue", "orders", "customers", "units")
    sql = f"SELECT {select}, ROUND(SUM(i.sale_price),2) revenue, COUNT(*) units, COUNT(DISTINCT i.order_id) orders, COUNT(DISTINCT i.user_id) customers {source} WHERE {where} AND DATE(i.created_at)>=@start AND DATE(i.created_at)<@end"
    if groups:
        sql += " GROUP BY " + ", ".join(groups)
    if request["dimension"] == "state":
        sql += " HAVING COUNT(DISTINCT i.user_id)>=5"
    if keys:
        sql += " ORDER BY " + (
            "month" if request["dimension"] == "month" else rank + " DESC, " + ", ".join(keys)
        )
    sql += " LIMIT @limit"
    return query(client, sql, params)


def run(root):
    client = bigquery.Client(project=Settings.load().google_cloud_project)
    cache = {}
    checks = []
    for path in sorted(root.glob("[0-9][0-9]-[12].json")):
        capture = json.loads(path.read_text())
        for evidence in capture.get("answer", {}).get("evidence", []):
            request = evidence["request"]
            signature = json.dumps([capture["user"], request], sort_keys=True)
            if signature not in cache:
                cache[signature] = oracle(client, request, capture["user"])
            expected = cache[signature]
            actual = evidence["rows"]
            error = ""
            try:
                assert len(actual) == len(expected), (len(actual), len(expected))
                for a, b in zip(actual, expected, strict=True):
                    for field, value in b.items():
                        if isinstance(value, float):
                            assert a[field] is not None and math.isclose(
                                a[field], value, rel_tol=1e-9, abs_tol=1e-8
                            ), (field, a[field], value)
                        else:
                            assert a[field] == value, (field, a[field], value)
            except AssertionError as exc:
                error = str(exc)
            checks.append(
                {
                    "turn": capture["id"],
                    "evidence": evidence["id"],
                    "passed": not error,
                    "error": error,
                    "expected": expected,
                }
            )
            print(capture["id"], evidence["id"], not error, flush=True)
    output = {
        "unique_queries": len(cache),
        "checks": checks,
        "method": "Independent EXISTS-based sales SQL and eligible-minus-recent customer sets for inactivity; no production compiler.",
    }
    (root / "oracle.json").write_text(json.dumps(output, indent=2))
    assert all(c["passed"] for c in checks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--results", type=Path, required=True)
    run(parser.parse_args().results)
