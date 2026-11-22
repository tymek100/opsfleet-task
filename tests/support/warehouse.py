"""A small adversarial contract fixture, independent of retrieval examples."""

SQL = """
CREATE TABLE fixture_products (
 product_id INTEGER, brand VARCHAR, category VARCHAR, product_name VARCHAR);
INSERT INTO fixture_products VALUES
 (11, 'Calvin Klein', 'Tops', 'Cedar top'),
 (12, 'Calvin Klein', 'Coats', 'Willow coat'),
 (13, 'Calvin Klein', 'Coats', 'Unsold coat'),
 (91, 'Levi''s', 'Denim', 'Hidden denim');
CREATE TABLE fixture_orders (order_id INTEGER, user_id INTEGER, order_status VARCHAR);
INSERT INTO fixture_orders VALUES
 (101, 1, 'Complete'), (102, 1, 'Complete'), (103, 2, 'Complete'),
 (104, 3, 'Cancelled'), (105, 4, 'Returned'), (106, 5, 'Complete'),
 (107, 6, 'Complete'), (108, 7, 'Complete'), (109, 8, 'Complete'),
 (110, 9, 'Complete'), (111, 2, 'Complete');
CREATE TABLE fixture_items (
 item_id INTEGER, order_id INTEGER, user_id INTEGER, product_id INTEGER,
 sale_price DECIMAL(12,2), purchased_at TIMESTAMP, item_status VARCHAR);
INSERT INTO fixture_items VALUES
 (1, 101, 1, 11, 10.10, '2026-01-01 00:00:00', 'Complete'),
 (2, 101, 1, 11, 20.20, '2026-01-01 00:00:00', 'Complete'),
 (3, 102, 1, 12, 30.30, '2026-03-31 23:59:59', 'Complete'),
 (4, 103, 2, 11,  5.05, '2026-02-01', 'Complete'),
 (5, 104, 3, 11, 1000, '2026-02-01', 'Complete'),
 (6, 105, 4, 12, 2000, '2026-02-01', 'Complete'),
 (7, 106, 5, 12, 3000, '2026-02-01', 'Returned'),
 (8, 107, 6, 12, 4000, '2026-02-01', 'Cancelled'),
 (9, 108, 7, 11, 5000, '2025-12-31 23:59:59', 'Complete'),
 (10, 109, 8, 11, 6000, '2026-04-01 00:00:00', 'Complete'),
 (11, 101, 1, 91, 9000, '2026-01-01', 'Complete'),
 (12, 110, 9, 91, 8000, '2025-01-01', 'Complete'),
 (13, 111, 2, 91, 7000, '2026-02-01', 'Complete');
"""

Q1 = "purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')"
