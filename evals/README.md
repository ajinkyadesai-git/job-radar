# Evals

57 questions that grade the Job Radar assistant (`questions.csv`): counts, rankings,
filters, salary, description search, resume fit, honesty and safety, plus 5 written by the
project owner (`Yours`). The working copy is the "Job Radar Eval Questions" sheet; this file
is exported from it.

Each question has a **check** that grades the answer automatically (see
`src/jobradar/evals/checks.py`). For data questions the right answer is recomputed by the
SQL in `expected` at run time, because the job data changes daily.

```
jobradar eval --truth-only        # check every right-answer query; no API cost
jobradar eval --only Safety       # one category, or IDs: --only C01,X02
jobradar eval                     # full run, about 15 minutes
```

Scores go to `results/<run>.md` and `results/latest.md` (committed). Full answers go to
`results/<run>.jsonl`, which stays on the laptop because resume-fit answers list skills from
the resume.
