# Slack welcome and collaboration context

The following welcome was supplied by the candidate. It is context, not an additional technical specification.

> Hey **Tymek Ilczyszyn** 👋 Welcome to the team's Slack workspace!
>
> We're excited to have you here. This channel is your **home base** for the technical assignment phase of your interview process — from getting started all the way through to submitting your solution.
>
> 📋 **Your Assignment**
>
> [Click here to view your assignment](https://opsfleet.slack.com/docs/T38KZJ5AM/F0A9MTCMS20)
>
> 💡 **How This Works**
> - Drop a message here whenever you're ready to start
> - Ask any questions about the assignment — technical or logistical
> - The team is following along in this channel, so you're never alone
> - If at any point you'd prefer to speak with a human, just say the word and someone from the team will jump in
>
> 🚀 Whenever you're ready — let's get going. **Good luck!**

The candidate reports being encouraged to ask many questions before and during the task and interprets this as a chance to demonstrate requirements gathering and client collaboration. The welcome itself invites questions but does not specify a required number.

## Client clarification: development and review credentials

Harry - AI Assistant, 12:42 PM (reply supplied by the candidate):

> @Tymoteusz Ilczyszyn for development and testing, you'll need your own GCP project and Gemini API key — Google provides 1 TB of free BigQuery processing per month, which is more than enough for this task. When the team reviews your submission, they'll use their own credentials, so just make sure your code is runnable on another machine with externally supplied credentials and that your setup instructions cover that clearly. Thanks, and good luck!

Confirmed decision: the candidate supplies their own development GCP project and Gemini API key; reviewers supply their own credentials. The repository must support external configuration and document setup on another machine. The free-tier statement above is preserved as part of the client's message, not an independently verified pricing guarantee.

## Client answers: access, privacy, metrics, deletion, and Golden Knowledge

Reply supplied by the candidate:

> @Tymoteusz Ilczyszyn great questions — here are the answers:
>
> 1. **Product access:** Access is brand-based — each manager can only analyze data for their own brands, and the CEO sees everything. The mapping between managers and brands is not in the dataset, so you can define whatever structure makes sense (e.g., a local config or access table). Two demo users with different brand permissions is perfectly fine for the prototype.
>
> 2. **Customer privacy:** You should never show names, emails, addresses, postal codes, or exact coordinates — not in output, and not to the LLM. For 'top customers' style questions, referring to customers by their internal `user_id` or a stable pseudonymous ID (e.g., a salted hash) is fine, so multi-turn follow-ups still work. State-level demographics are allowed, but only in aggregates — not tied to identifiable individuals.
>
> 3. **Metric definitions:** There are no fixed company-wide definitions. Document sensible defaults (e.g., revenue excludes cancelled and returned orders; churn = no purchase in the last 90 days), state which definition was used in each answer, and allow users to override. Your approach of clarifying ambiguous requests sounds right.
>
> 4. **Report deletion:** Showing the exact list of matching reports and requiring explicit confirmation before proceeding is exactly the right approach. Deletion is permanent — hard delete, no recovery. For 'reports mentioning Client X', interpreting it as any entity named in a report (brand, category, etc.) is fine since thelook has no B2B clients.
>
> 5. **Golden Knowledge Bucket:** This is primarily a design requirement — you don't have access to a real bucket. Define the Trio format yourself (Question → SQL Query → Analyst Report), seed a small sample set, and explain in your HLD how you'd populate and query it over time. Including a working retrieval demo in the prototype is welcome but not required.
>
> Hope that clears things up — let us know if anything else comes up. Good luck!

## Follow-up confirmation: Golden Knowledge

Reply supplied by the candidate:

> @Tymoteusz Ilczyszyn there is no existing bucket or sample trios to use — it's a theoretical construct for this assignment. Define the Trio format yourself (Question → SQL Query → Analyst Report), create a few illustrative examples to seed it, and in your HLD explain how you'd populate and query it over time in production. A working retrieval demo in the prototype is a nice touch but not required. Thanks, and good luck!

This confirms the existing plan: define the Trio format, supply illustrative seed examples, and document production population and retrieval. No external bucket access is expected; a working retrieval demo remains optional.

## Client answers: demo priorities and production requirements

Reply supplied by the candidate; mention formatting normalized:

> @Tymoteusz Ilczyszyn, great questions — here are the answers:
>
> 1. **Demo priorities:** The FAQ includes a full set of example questions that cover the agent's core capabilities. Strong ones to prioritize: **"List the top 10 best sellers by revenue and by number of customers"**, **"Why did our churn rate spike last month?"**, and **"Create a report for Q1 including insights and action items for Q2"** — they cover SQL reasoning, multi-step analysis, and report generation in one flow. Looping in @Roi Hezkiyahu if there are specific scenarios they'd like to see.
>
> 2. **"Why" questions:** A breakdown of measurable drivers with clearly labelled hypotheses is a solid approach — being transparent that transaction data shows patterns rather than definitive causes (e.g., "data suggests X, which may be influenced by Y") is exactly the right framing. Looping in @Roi Hezkiyahu to confirm this meets the bar.
>
> 3. **Brand-scoped customer metrics:** Yes — calculating spend and churn using only a manager's authorized brands is the intended behavior.
>
> 4. **Reporting periods:** UTC and calendar quarters by default are fine. Asking for clarification when the time period materially affects the answer is a good approach.
>
> 5. **Saved reports:** Save only when explicitly requested. Reports are private to their creator — the CEO's broader access applies to analytics, not to reports saved by others.
>
> 6. **Production expectations:** Design for roughly 100 active managers per day, ~10 questions per manager per day, ~1 saved report per manager per day, and ~1M new rows of data daily. Concurrently, only a few users active at the same time. Response time targets: 10–30 seconds for simple questions, 1–2 minutes for long reports. Cost budget: $1 per question (easily configurable). No specific GCP region or data-residency requirements.
>
> 7. **Knowledge and tone management:** Tone/persona changes must be doable by a non-technical user without editing code or redeploying — changes should pass an automated quality gate before going live, no manual approval step required. A simple editor/reviewer workflow for Golden Knowledge examples sounds appropriate; @Roi Hezkiyahu can weigh in on the specifics.
>
> 8. **Retention:** Chat history: 90 days. Saved reports: kept until the user deletes them (hard delete, no recovery window). Audit log: 1 year.
>
> Thanks, and good luck!
