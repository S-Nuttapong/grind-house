---
version: v2
---
Extract facts from one job posting. Use only what the posting says.

role is a slug from the schema, or unknown.
level is intern, junior, mid, senior, staff, principal, lead, or manager.
Take level from the title or from explicit seniority wording.
Do not infer level from years of experience alone. When in doubt, unknown.
workplace, job_type, currency, interval, country, and posted are unknown when absent.
city is empty when absent.
Each evidence field is a verbatim substring of the title or description, or empty.
Do not guess.

Pay is base pay for this role only. Ignore bonus, commission, equity, allowances, benefits, budgets, revenue, and funding.
minimum and maximum are decimal strings, or empty when no amount is stated.
A single stated amount sets both minimum and maximum to that amount.
"Up to X" sets only maximum. "From X", "X+", or "at least X" sets only minimum.
฿40,000 per month means minimum 40000, maximum 40000, currency THB, interval monthly.
฿55,000 – ฿80,000 per month means minimum 55000, maximum 80000, currency THB, interval monthly.
up to ฿80,000 per month means minimum empty, maximum 80000, currency THB, interval monthly.
from ฿40,000 per month means minimum 40000, maximum empty, currency THB, interval monthly.
Expand shorthand such as 80k or 1.2M, and normalize digit grouping such as 1,20,000 or 1.200.000.
currency is the ISO 4217 code for the symbol, abbreviation, or code used. For a symbol shared by several currencies, such as $, kr, or ¥, use the posting's country.
interval comes from the posting's own wording for the pay period. Use unknown when none is stated. Never infer the interval from the size of the amount.
When several ranges are listed by location or level, use the one for the posting's own location. If none matches, use the first.
evidence_pay is the verbatim text the amounts came from. It is never empty when an amount is set.
