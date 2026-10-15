---
version: v3
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
The same rules apply in any currency and any pay period. Examples:
$120,000 per year means minimum 120000, maximum 120000, currency USD, interval yearly.
£45,000 - £60,000 per annum means minimum 45000, maximum 60000, currency GBP, interval yearly.
up to $80 an hour means minimum empty, maximum 80, currency USD, interval hourly.
from SGD 6,000 a month means minimum 6000, maximum empty, currency SGD, interval monthly.
Expand shorthand such as 80k or 1.2M, and normalize digit grouping such as 1,20,000 or 1.200.000.
currency is the ISO 4217 code for the symbol, abbreviation, or code used. For a symbol shared by several currencies, such as $, kr, or ¥, use the posting's country.
interval comes from the posting's own wording for the pay period. Use unknown when none is stated. Never infer the interval from the size of the amount.
When several ranges are listed by location or level, use the one for the posting's own location. If none matches, use the first.
evidence_pay is the verbatim text the amounts came from. It is never empty when an amount is set.
