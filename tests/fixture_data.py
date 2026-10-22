"""Execute compiled SQL against synthetic data; BigQuery compatibility tested separately."""

from datetime import date

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.expressions.core import Expression

from retail_agent.bigquery import QueryResult
from retail_agent.budget import Budget
from retail_agent.models import Scalar
from retail_agent.observability import Trace
from retail_agent.queries import CompiledQuery

DATA = """
CREATE TABLE products(id INTEGER, brand VARCHAR, category VARCHAR, name VARCHAR);
INSERT INTO products VALUES (1,'Calvin Klein','Jeans','Alpha jeans'),
 (2,'Levi''s','Jeans','Beta jeans'),(3,'Calvin Klein','Tops','Alpha top');
CREATE TABLE users(id INTEGER,state VARCHAR,first_name VARCHAR,email VARCHAR);
INSERT INTO users VALUES (1,'CA','CANARY_NAME','canary@example.test'),(2,'CA','Canary2','private2@example.test'),
 (3,'NY','Canary3','private3@example.test'),(4,'CA','Canary4','p4@example.test'),
 (5,'CA','Canary5','p5@example.test'),(6,'CA','Canary6','p6@example.test');
CREATE TABLE orders(order_id INTEGER,user_id INTEGER,status VARCHAR);
INSERT INTO orders VALUES (10,1,'Complete'),(11,1,'Complete'),(12,2,'Complete'),
 (13,3,'Returned'),(14,3,'Complete'),(15,4,'Complete'),(16,5,'Complete'),
 (17,6,'Complete'),(18,2,'Cancelled'),(19,1,'Complete'),(20,1,'Complete');
CREATE TABLE order_items(id INTEGER,order_id INTEGER,user_id INTEGER,product_id INTEGER,
 sale_price DOUBLE,created_at TIMESTAMP,status VARCHAR);
INSERT INTO order_items VALUES
 (1,10,1,1,100,'2026-01-01','Complete'),
 (2,10,1,2,900,'2026-01-01','Complete'),
 (3,11,1,1,50,'2026-02-01','Complete'),
 (4,12,2,3,50,'2026-02-02','Complete'),
 (5,13,3,1,600,'2026-02-03','Returned'),
 (6,14,3,1,700,'2026-02-04','Returned'),
 (7,15,4,3,50,'2026-03-01','Complete'),
 (8,16,5,3,50,'2026-03-01','Complete'),
 (9,17,6,3,50,'2026-03-01','Complete'),
 (10,18,2,1,999,'2026-03-01','Complete'),
 (11,19,1,2,1000,'2026-05-20','Complete'),
 (12,20,1,1,80,'2026-07-01','Complete');
"""


def literal(value: str | int | bool | date | list[str] | list[int]) -> Expression:
    if isinstance(value, list):
        return exp.Array(expressions=[literal(v) for v in value])
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, int):
        return exp.Literal.number(value)
    if isinstance(value, date):
        return exp.Cast(this=exp.Literal.string(value.isoformat()), to=exp.DataType.build("DATE"))
    return exp.Literal.string(value)


class FixtureExecutor:
    def execute(self, query: CompiledQuery, budget: Budget, trace: Trace) -> QueryResult:
        budget.query()
        tree = sqlglot.parse_one(query.sql, read="bigquery")
        for param in list(tree.find_all(exp.Parameter)):
            param.replace(literal(query.parameters[param.name]))
        for table in tree.find_all(exp.Table):
            table.set("catalog", None)
            table.set("db", None)
        with duckdb.connect() as connection:
            connection.execute(DATA)
            cursor = connection.execute(tree.sql(dialect="duckdb"))
            columns = [str(c[0]) for c in cursor.description]
            rows: list[dict[str, Scalar]] = [
                dict(zip(columns, row, strict=True)) for row in cursor.fetchall()
            ]
        trace.emit("fixture_query", rows=len(rows))
        return QueryResult(rows, "fixture_job", 0)
