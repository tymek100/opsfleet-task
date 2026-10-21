# What the app has to do

Build a command-line chat assistant that helps retail executives understand business performance without writing SQL. A user asks a question, the assistant queries BigQuery, explains the findings, and can turn them into a saved report with suggested actions. Users can ask follow-up questions within the same conversation.

## Example experience

1. Ask: “Compare sales of product X and product Y last quarter.”
2. The assistant clarifies any ambiguity, queries the data the user is allowed to access, and explains the comparison.
3. Ask: “What might explain the difference?” The assistant investigates supporting metrics and distinguishes observed evidence from possible explanations.
4. Ask: “Save a report with recommendations for next quarter.”
5. Ask: “Delete the reports from this conversation.” The assistant lists the exact matching reports, requests explicit confirmation, and deletes only those confirmed reports owned by that user.

## What data it uses

The required BigQuery dataset is `bigquery-public-data.thelook_ecommerce`. The four tables are `orders`, `order_items`, `products`, and `users`.

The production design must also use a “Golden Knowledge” collection: examples of questions, SQL, and reports approved by human analysts. These examples teach the assistant business definitions and analytical approaches; current numbers still come from current queries.

## Required working prototype

- Natural-language analysis, follow-up conversation, and reports with insights and action items.
- Dynamic SQL execution against BigQuery and explanations of the available database structure.
- Brand-based access: managers see their assigned brands, the CEO sees all brands, and privacy restrictions apply to everyone. Two demo managers with different permissions are acceptable.
- A saved-report library with ownership checks, an exact preview, and explicit confirmation before permanent hard deletion.
- Bounded recovery from invalid SQL, empty results, rate limits, and service failures.
- Useful diagnostic events that explain failures without leaking sensitive data.
- A CLI and setup instructions sufficient to run it on another machine.

## Required production design

Explain all eight requirements, including how to retrieve and maintain Golden Knowledge, remember user preferences, improve the system through reviewed feedback, evaluate answer quality and UX, and let non-developers change report tone without redeployment. Include specific cloud services, storage, communication paths, security boundaries, and an architecture diagram.

The brief explicitly makes requirements 2, 3, 5, and 7 mandatory in the prototype. Golden Knowledge retrieval, learning, evaluation infrastructure, and persona administration can be design-only. The client requires a defined Trio format and a small seeded example collection; working retrieval is optional. Charting, email, and web search are future extensions, not required prototype tools.

## What a good answer looks like

It answers the user's actual question, identifies the period and metric definitions, supports numbers with query evidence, and explains relevant limitations. It does not invent reasons for changes: transaction data can show associations without proving causation. Document sensible metric defaults, state the definition used in each analytical answer, and allow users to override it. The client suggests excluding cancelled/returned purchases from revenue and a 90-day inactivity window for churn.

## Submission

A public GitHub repository containing runnable code, setup and example-run instructions, the architecture diagram, and a detailed technical explanation. Explain the framework choice and honestly state your own experience with it. The stated effort budget is 6–12 hours, so prioritize a small, well-tested prototype and a clear production design.

## Confirmed customer privacy rules

Never send names, emails, addresses, postal codes, or exact coordinates to the LLM or include them in output. Customer rankings may use internal user IDs or stable pseudonyms for follow-ups. State demographics must be aggregated and must not be tied to individual customers.

## Additional client decisions

- Prioritize top-10 product rankings by revenue and customer count, investigation of a possible monthly churn spike, and a Q1 report with Q2 action items.
- Use UTC and calendar quarters; clarify periods when material. Customer spend and churn use only the user's authorized brands.
- Save reports only on explicit request. They are private to their creator, including against CEO access.
- Production targets: about 1,000 questions and 100 saved reports daily, 1 million new rows daily, and a few concurrent users. Aim for 10–30 seconds for simple answers and 1–2 minutes for long reports, with a configurable USD 1 question budget.
- Tone changes use a non-technical editing interface and an automated quality gate before publishing, with no manual approval. Golden examples use an editor/reviewer workflow.
- Retain chats for 90 days, saved reports until permanent owner deletion, and audit logs for one year.
- No specific region or residency requirement. Roi may still provide scenario and evaluation refinements; these do not block implementation.
