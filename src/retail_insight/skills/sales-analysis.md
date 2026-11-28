# Sales analysis

- Use `order_items` as the purchase grain. Join `products` on `product_id = products.id` and `orders` on `order_id = orders.order_id`.
- Unless the user requests another population, qualifying sales exclude `Cancelled` and `Returned` at both item and order level. State that definition briefly when relevant.
- Revenue is `SUM(order_items.sale_price)`. Count orders and customers with distinct IDs. AOV is qualifying revenue divided by qualifying distinct orders, with a zero-denominator guard.
- Filter purchases using `order_items.created_at` and UTC `[start, end)` boundaries. Current status fields do not reconstruct historical status changes or cash collected.
- Query separate rankings separately. Use a stable ID tie-break and mention material ties without claiming the cutoff proves a meaningful difference.
- Product prices or categories alone do not prove why revenue changed. Query supporting measures before making that claim. The source does not specify currency.
