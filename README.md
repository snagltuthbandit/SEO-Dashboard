# UNA AI Citation Tracker (pilot)

Tracks whether University of North Alabama is mentioned — and how — when
ChatGPT, Claude, Gemini, and Perplexity answer unbranded prospective-student
queries. Generates a static local HTML dashboard, trended weekly.

Built as a pilot for UNA. Re-pointing this at another client (Rolling Hills,
Show Hope, etc.) should be a config swap — edit `config/prompts.yaml` and
`config/competitors.yaml` — not a rebuild.

## Setup

```bash
cd una-citation-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
```

## Run manually

```bash
python3 src/runner.py         # calls all 4 engines x all prompts, writes to db/citations.db
python3 src/dashboard.py      # regenerates output/dashboard.html
open output/dashboard.html
```

Run a subset of engines while testing (e.g. you only have an OpenAI key so far):

```bash
python3 src/runner.py --engines openai anthropic
```

## Schedule weekly via cron

```bash
crontab -e
# Monday 6am:
0 6 * * 1 /full/path/to/una-citation-tracker/run.sh >> /full/path/to/una-citation-tracker/run.log 2>&1
```

`run.sh` runs `runner.py` then `dashboard.py` in sequence. Daily runs are
unnecessary burn — AI outputs don't drift meaningfully day to day.

## Config

- `config/prompts.yaml` — the unbranded prompt set. Add/refine with real
  enrollment-marketing keyword research; this starter set is not final.
- `config/competitors.yaml` — brand + competitor names/aliases/domains.

Both are plain YAML, read fresh on every run — no code changes needed to
retarget prompts or competitors.

## Known limitations (read before trusting the dashboard)

- **Alias ambiguity**: `competitors.yaml` includes bare aliases like
  `"Alabama"` and `"Bama"` for University of Alabama. Because prompts
  themselves reference "Alabama" as a state name, the parser's word-boundary
  match will over-count University of Alabama mentions whenever the state is
  mentioned generically, not just when the school is. Spot-check this
  before reporting share-of-voice numbers; consider narrowing aliases if it
  proves noisy in practice.
- **`is_recommended` is a naive heuristic**: proximity (~50 chars) to
  phrases like "recommend" or "top choice." It will both over- and
  under-flag. Treat it as directional, not precise. LLM-as-judge scoring is
  a deferred v2 improvement.
- **Position buckets** (`first`/`early`/`mid`/`late`/`not_mentioned`) are
  derived from character offset, not semantic structure — a school named in
  a long caveat/disclaimer sentence early in the response scores the same
  as one in a strong opening recommendation.
- **No web grounding for OpenAI/Anthropic/Gemini** — these reflect model
  training data, not live search results. Perplexity is the only
  search-grounded engine and the most directly comparable to real AI-search
  behavior; its `citations` array is cross-checked against `una.edu` as a
  stronger signal than a text mention.
- **Manually verify ~10 responses** against parser output before trusting
  the dashboard, per the pilot's success criteria.

## Explicitly out of scope for this pilot

- Google AI Overviews (no public API — would need SERP-scraping via
  DataForSEO/SerpApi; revisit as v2)
- LLM-as-judge recommendation-strength scoring
- Multi-client dashboard support
- Email/Slack digest delivery

## Deployment (GitHub Actions + Netlify, free)

The dashboard is a static HTML file, so hosting is free. Collection runs
weekly in GitHub Actions; Netlify serves the generated `output/dashboard.html`.
**Netlify only ever receives the static HTML — API keys and the raw response
DB never leave the private repo.**

Moving parts:

- `.github/workflows/weekly.yml` — weekly cron (Mon ~06:00 Central). Runs the
  collector, then commits the updated `db/citations.db` + `output/dashboard.html`
  back to the repo. Only triggers on schedule / manual dispatch, so its own
  commit can't re-trigger it.
- `netlify.toml` — publishes `output/`, serves `dashboard.html` at the site root.
- `db/citations.db` is committed (not gitignored): in this deployment the repo
  is the durable store for the week-over-week trend history.

**One-time setup:**

1. **Create a private GitHub repo** on the 5by5 account, then push:
   ```bash
   git remote add origin git@github.com:<org>/una-citation-tracker.git
   git branch -M main && git push -u origin main
   ```
2. **Add API keys** as repo secrets (Settings → Secrets and variables →
   Actions): `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`. To enable more engines,
   add `OPENAI_API_KEY` / `PERPLEXITY_API_KEY` and extend the `--engines` line
   in `weekly.yml`.
3. **Connect Netlify** (Add new site → Import from Git → pick the repo).
   `netlify.toml` is auto-detected; no build command needed.
4. **Test the loop**: Actions tab → "Weekly citation run" → Run workflow. This
   collects, commits, and triggers a Netlify deploy without waiting for Monday.

## Re-pointing at a new client

1. Copy `config/prompts.yaml` and `config/competitors.yaml`, edit for the
   new brand + competitor set + query set.
2. Point `db.DB_PATH` (in `src/db.py`) at a new SQLite file if you want
   separate history per client, or keep one DB and add a `client` column if
   you outgrow file-per-client (not needed for the pilot).
3. Re-run `run.sh`.
