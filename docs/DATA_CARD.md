# Data card

GigBid was built without a provided starter kit. Following the TA's guidance (Classroom, 10 Nov 2026), the marketplace
simulator (GigSim) and every persona were built for this project, and real job postings come from public Kaggle
datasets. **Every record carries a `source` field: `synthetic` or `kaggle:<file>`.** Nothing synthetic is presented as real.

## What is in the repo

| Data | Where | Real or synthetic | Size |
|---|---|---|---|
| Persona portfolios (CV as Markdown and PDF, case studies, repo READMEs and code, client reviews, past proposals with outcomes) | `data/personas/{ai_ml,fullstack,data_analyst}/` | **Synthetic** (`data/generators/build_corpus.py --seed 7`) | AI/ML: 20 case studies, 10 repos; Full-stack: 21 / 17; Data analyst: 20 / 12 |
| Gold project→skill map (used only for scoring, never ingested) | `data/personas/_ground_truth/projects.json` | Synthetic | — |
| GigSim clients with hidden preferences | `gigsim/data/clients.json` | Synthetic | 420 clients |
| GigSim jobs (fit, weak-fit, scam, planted-injection, duplicate) | `gigsim/data/jobs.json`, `history_jobs.json` | Synthetic text; budgets anchored on Kaggle price statistics when available | 630 live jobs |
| Dev set with gold labels | `evals/datasets/dev_<persona>.jsonl` | Synthetic | 210 jobs per persona (630 total); 31 planted injections, 64 scams |
| Hidden set | `evals/datasets/hidden/` | Synthetic | git-ignored; never used for tuning |
| Marketplace policy pack (Compliance Guard rules) | `data/policy_pack/` | Written for this project from public marketplace rules (no off-platform contact or payment, no fabricated experience, no guarantees, fair use of automation) | — |
| Real job postings (pricing statistics, extra GigSim stream) | `data/raw/` → `data/processed/market_stats.json` | **Real**, Kaggle | git-ignored; regenerate with `make data` |

## Kaggle sources and licences

`data/generators/import_kaggle.py` reads whichever of the TA-listed Upwork job-posting datasets is placed in
`data/raw/` (e.g. asaniczka "Upwork Job Postings" 50k/200k, ahmedmyalo 60k). Columns are auto-detected; each kept row is
tagged `source: kaggle:<file>`. The raw CSVs are **not redistributed** in this repository; download them from Kaggle
under their own licences and attribution terms, as shown on each dataset page. They are used only to derive price quantiles per
category and a stream of realistic postings inside the simulator, never to train a model.

## Preprocessing

* Personas: generated from templates plus seeded randomness; gold labels (which project proves which skill, which jobs
  are scams or injections, the fair price band) are known by construction, so retrieval and decision metrics need no
  hand labelling.
* Chunking: structure-aware chunks (`rag/ingest/chunkers.py`, 700 characters, 100 overlap) with metadata on every chunk:
  persona, type, project, skills, date, client industry and, for proposals, outcome.
* PII: `common/pii.py` masks emails, phone numbers and URLs in logs and error bodies.

## Limitations (read before trusting a number)

* **Synthetic personas and clients.** The simulated client's reply decision is an LLM plus rules over hidden
  preferences (`gigsim/client_model.py`); GigSim reply rates measure fit with that model, not with real clients.
* **Gold evidence is per persona and per project,** so Recall@5 is capped at the number of gold items; very short
  jobs have one or two gold items, which makes their recall noisy.
* **Small evaluation runs on the free tier.** Groq's free tier allows 8,000 tokens per minute per model, and one
  analysed job costs about 13k tokens (about 29k for a drafted proposal). LLM-based studies were therefore run on
  subsets; each results file records its sample size in `provenance`.
* English only; three personas; one marketplace (GigSim). Live Upwork mode is wired through the same port but was
  not run (no account), so there are no live funnel numbers.
