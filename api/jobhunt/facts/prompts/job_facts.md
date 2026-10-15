---
version: v1
---
Extract facts from one job posting. Use only what the posting says.

role is a slug from the schema, or unknown.
level is intern, junior, mid, senior, staff, principal, lead, or manager.
Take level from the title or from explicit seniority wording.
Do not infer level from years of experience alone. When in doubt, unknown.
workplace, job_type, currency, interval, country, and posted are unknown when absent.
minimum and maximum are decimal strings, or empty when absent.
city is empty when absent.
Each evidence field is a verbatim substring of the title or description, or empty.
Do not guess.
