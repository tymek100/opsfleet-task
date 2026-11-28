---
name: period-comparison
description: Compare revenue or other metrics across months, quarters or other periods, including partial periods, percentage changes and zero baselines.
metadata:
  audience: analyst
  version: "4"
---

# Period comparison

Use comparable periods, populations, grain and metric definitions. Resolve materially missing years or reporting windows before a broad investigation. Disclose or adjust a partial-versus-full-period comparison.

Use UTC [start, end) boundaries. Readable labels such as "January through March" can use inclusive calendar dates, but do not describe March 31 as an exclusive quarter endpoint.

Anchor now, MTD and YTD to trusted now_utc/today_utc. Source MAX(timestamp) is data coverage, not today. Exclude future rows from every current-period total and breakdown using the same cutoff. Explicit future-period requests are distinct from realized performance as of now.

Qualifying sales exclude Cancelled/Returned at both order and item levels; they are not Complete-only. Define requested status overrides explicitly. Preserve selected cohorts on follow-ups.

Absolute change = later - earlier. Percentage change = change / earlier; a zero baseline makes it undefined. Percentage-point change is the difference between proportions expressed as percentages. Compute from full precision, then round for display.

Compute distinct customer/order unions across periods instead of summing overlapping counts. Keep empty results, zero and undefined distinct.

Verify a claimed increase or decline before explaining it. More active customers does not establish acquisition; first purchases across scoped history are needed. A measured contribution does not prove a marketing or other business cause. Use revenue-driver-analysis when price, quantity or customer contributions are relevant; otherwise report the supported comparison without extra metrics.
