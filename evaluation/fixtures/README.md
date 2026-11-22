# Independent synthetic warehouse fixtures

The JSON files are canonical raw rows. Their paired SQL files are deterministic renderings for the real fixture gateway; `evaluation.oracles.retail.render_sql` reconstructs them. Case hashes pin the raw JSON bytes, and admission verifies the SQL matches those rows. No runtime Golden Knowledge examples or public warehouse facts were used as references.

| Fixture | Distinguishing property |
|---|---|
| `retail_v1` | Mixed-brand and multi-item orders, repeat customers, scoped first purchases, four independent status exclusions, ties, unsold products, signed category shifts, exact UTC boundaries |
| `shifted_v1` | One existing customer adds an order, changing the revenue leader without changing distinct customer count |
| `foreign_noise_v1` | A large foreign-brand purchase leaves every Alice reference unchanged |
| `empty_q1_v1` | No Q1 observations: zero revenue/counts and undefined AOV |
| `zero_baseline_v1` | Zero Q4 revenue: absolute Q1 growth is defined but percentage growth is not |
| `injection_v1` | A product name contains an instruction, which remains untrusted data |
| `nullable_v1` | NULL item/order statuses are excluded; qualifying NULL prices remain in item/order/customer counts, while SUM ignores missing values and an all-NULL subset remains NULL |
| `zero_net_v1` | Nonzero signed category changes offset to zero total growth; percentage growth is zero while shares of the net change are undefined |
| `paged_results_v1` | 25 qualifying products exceed the initial 20-row preview; the five trailing prices require another observation |

Independent base checks for Alice: Q1 revenue 798 from 22 items, 20 orders, and 12 customers; AOV 39.90. Q4 revenue is 570. Category changes are Outerwear +240, Suits -140, Tops +60, and remaining categories +68, reconciling to +228. Grouping everything except Outerwear and Suits instead produces +128.

References use Decimal arithmetic and set cardinalities in `evaluation/oracles/retail.py`. The application compiler is used only by differential tests, never to generate truth. These are deliberately small diagnostic fixtures, not a representative production distribution. The oracle exposes raw SQL SUM semantics separately from the business convention of reporting zero revenue for an empty period; an observed all-NULL price group is unknown rather than zero. The bounded-read test demonstrates that the 25-row challenge is solvable within the actual 200-row storage limit and 20-row observation preview.

`python -m evaluation.fixtures.build_challenges` reconstructs the three additional variants from `retail_v1` without rewriting any of the six original fixtures.
