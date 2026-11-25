-- Synthetic retail data for the local demo backend; never current BigQuery facts.
-- Adapted from the repository's small synthetic fixture, then frozen here.
-- Adds an unsold catalog product and a second eligible item in an existing order.
-- No live TheLook data or customer contact/geographic fields are present.
CREATE TABLE fixture_products (
    product_id INTEGER, brand VARCHAR, category VARCHAR, product_name VARCHAR
);
INSERT INTO fixture_products VALUES
    (1, 'Calvin Klein', 'Jeans', 'Alpha jeans'),
    (2, 'Levi''s', 'Jeans', 'Beta jeans'),
    (3, 'Calvin Klein', 'Tops', 'Alpha top'),
    (4, 'Calvin Klein', 'Jackets', 'Gamma jacket');

CREATE TABLE fixture_orders (order_id INTEGER, user_id INTEGER, order_status VARCHAR);
INSERT INTO fixture_orders VALUES
    (10, 1, 'Complete'), (11, 1, 'Complete'), (12, 2, 'Complete'),
    (13, 3, 'Returned'), (14, 3, 'Complete'), (15, 4, 'Complete'),
    (16, 5, 'Complete'), (17, 6, 'Complete'), (18, 2, 'Cancelled'),
    (19, 1, 'Complete'), (20, 1, 'Complete');

CREATE TABLE fixture_items (
    item_id INTEGER, order_id INTEGER, user_id INTEGER, product_id INTEGER,
    sale_price DOUBLE, purchased_at TIMESTAMP, item_status VARCHAR
);
INSERT INTO fixture_items VALUES
    (1, 10, 1, 1, 100, '2026-01-01', 'Complete'),
    (2, 10, 1, 2, 900, '2026-01-01', 'Complete'),
    (3, 11, 1, 1, 50, '2026-02-01', 'Complete'),
    (4, 12, 2, 3, 50, '2026-02-02', 'Complete'),
    (5, 13, 3, 1, 600, '2026-02-03', 'Returned'),
    (6, 14, 3, 1, 700, '2026-02-04', 'Returned'),
    (7, 15, 4, 3, 50, '2026-03-01', 'Complete'),
    (8, 16, 5, 3, 50, '2026-03-01', 'Complete'),
    (9, 17, 6, 3, 50, '2026-03-01', 'Complete'),
    (10, 18, 2, 1, 999, '2026-03-01', 'Complete'),
    (11, 19, 1, 2, 1000, '2026-05-20', 'Complete'),
    (12, 20, 1, 1, 80, '2026-07-01', 'Complete'),
    (13, 10, 1, 1, 25, '2026-01-01', 'Complete');
