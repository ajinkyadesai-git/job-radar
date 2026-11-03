# Labeling guide

The fit model learns from your own decisions. Labels are personal, so they live in a private
Google Sheet and in git-ignored files under `config/labels/`, never in the repo.

## What a label means

| Label | Meaning | Counts as a fit? |
|---|---|---|
| Would apply | You would apply to this posting today | Yes |
| Would skip | You would not apply | No |

Seed labels from past applications follow the same rule: if you applied, it was a fit,
whatever happened next. Rejected, interviewing and offer all count as a fit, because the
model predicts *your* interest, not the employer's answer.

Rules for edge cases:

1. Judge the posting as it is today, not whether you have time to apply.
2. Right role, wrong location you would never move to: **Would skip**.
3. Right role, seniority one level off either way: **Would apply** if you would really send it.
4. Unsure after 20 seconds: open the link once; still unsure, skip the row and move on.

## Daily routine (15 minutes)

1. **Get the queue (2 min).** In Databricks, open the saved query `label_queue`
   (from [`sql/label_queue.sql`](../sql/label_queue.sql)), set `day`, run it, and copy the
   40 rows into **Seed Labels (private) > Daily Labels**, columns B to G.
2. **Label (11 min).** Put today's date in column A and pick **Would apply** or
   **Would skip** in column H. Decide from the title, company and location; open the link only
   when unsure. About 15 seconds a row.
3. **Log it (2 min).** Note the count in the Program Tracker (T40). Target: 40 a day, about
   200 by Nov 8, with at least 50 marked Would apply.

## Seed labels from your job hunt tracker

Export your tracker (applied, rejected and interviewing roles) and paste it into
**Seed Labels (private) > Applications** with these columns:

| Column | Format | Example |
|---|---|---|
| Company | Company name as you know it | Stripe |
| Job title | Title as posted | Analytics Engineer |
| Job link | Posting URL, if you kept it | https://boards.greenhouse.io/stripe/jobs/123 |
| Date applied | YYYY-MM-DD | 2026-10-15 |
| Outcome | Applied, no answer / Rejected / Interviewing / Offer / Skipped | Rejected |
| Notes | Optional | Referred by a friend |

Map your tracker's statuses onto the five outcomes; withdrawn applications count as
"Applied, no answer". A Greenhouse or Ashby job link lets the model match the exact posting;
without one it learns from the title and company only, which still helps. Companies outside
`config/companies.yaml` are fine for the same reason.

At training time (M4) both tabs are exported as CSV to `config/labels/`, which git ignores.
