# TalentTicker

**A stock ticker for the early-career software job market.**

Skills go up and down like share prices. You can see which ones companies are
asking for more than they used to, where the jobs are, what those companies are
actually trying to build, and get an email within minutes when a new role opens.

Scope is deliberately narrow: **software engineering roles in the United States
asking for 0 to 4 years of experience.** Every number comes from job postings
that companies published themselves.

---

## Why it exists

The usual advice is to apply to more jobs. That does not work — people send
hundreds of applications into a void. The more useful question is the one most
people skip: *what is the market actually asking for right now, and what is it
going to ask for next?*

That question is answerable. Companies publish their job postings in structured
form, they say exactly which skills they want, and they say what problem the
team is solving. Nobody reads four hundred of them. This does.

---

## What it does

### 1. Alerts you within minutes of a job going up

Companies publish to their applicant systems before those jobs reach LinkedIn
or Indeed. TalentTicker reads those systems directly every five minutes and
diffs against what it has already seen.

Twenty thousand open jobs would be spam, so nothing is sent unless it matches a
**watchlist** you defined — "entry-level backend, Massachusetts or remote,
mentions Go or Kubernetes, sponsorship not ruled out". Matches are emailed
straight away, with the sponsorship answer in the message.

### 1a. Where the jobs come from

There is no single feed of US software jobs, so this reads several, and the
distinction between them matters:

| Source | What it gives us |
|---|---|
| **Greenhouse, Ashby, Lever** | Full descriptions and real publish dates. Most startups and mid-size tech. |
| **Workday** | The same, for large employers — NVIDIA, Salesforce, Adobe and much of the Fortune 500. Token is `tenant:pod:site` from the careers URL. |
| **Amazon** | Its own platform, with full descriptions. Over a thousand early-career roles on its own. |
| **Community new-grad boards** | Second-hand. Title and link only, no description. Fills the gap for employers with no readable feed — Google, TikTok, SpaceX. |

**Direct sources always win.** The aggregated boards are useful for reach, but
they lag behind the company's own posting and carry no description. So every
aggregated row is resolved back to its origin: if the apply link points at a
Greenhouse, Ashby, Lever, Workday or Amazon posting we already hold, the
duplicate is dropped. When a direct posting arrives later, it deletes the
aggregated copy it supersedes.

Rows without a description are marked `has_content = 0`. They appear in the job
list and still fire alerts, but they are kept out of the skills and sector
figures — counting them would add to every denominator while never contributing
a skill, quietly dragging every percentage down.

**Finding more boards.** Rather than hand-guessing tokens, `tt discover` reads
the aggregated boards, looks at where each apply link actually points, and works
backwards to the board behind it. A link to `job-boards.greenhouse.io/twitch/...`
means Twitch has a Greenhouse board worth reading directly. Each candidate is
fetched to confirm it is real before being added.

```bash
.venv/Scripts/python -m tt discover          # report what is missing
.venv/Scripts/python -m tt discover --add    # write them into companies.yml
```

### 1b. Visa sponsorship

For anyone on OPT or an F-1 this is the first question, not the last. Every
posting is read for what it says about sponsorship and gets one of four answers:

| Answer | Meaning |
|---|---|
| **Sponsors** | The posting says it will sponsor or help with a visa |
| **No sponsorship** | It says it will not, or requires citizenship |
| **Clearance required** | A US security clearance is needed, which rules out most non-citizens in practice |
| **Not stated** | Nothing was said — by far the most common, and *not* a no |

Hover any badge for the exact sentence it was decided on. The job list filters
on it, and so do watchlists, so alerts can skip roles that are already closed
to you.

Two traps this has to avoid, both of which produced badly wrong answers before
they were handled:

- **The equal-opportunity paragraph.** Nearly every posting says "regardless of
  race, colour, religion, national origin, citizenship…". Searching for
  "citizenship" marks the entire market as closed. Those sentences are excluded
  first.
- **Export-control boilerplate.** Also near-universal, also not about
  sponsorship. It is deliberately ignored.

```bash
.venv/Scripts/python -m tt sponsorship
```

### 2. The skills ticker

Every skill gets a row:

| Column | Meaning |
|---|---|
| Share | Percentage of early-career US software postings that mention it |
| Jobs | How many postings, raw count |
| Change | Movement against the previous window of equal length |
| Sparkline | Twelve months of share |

Click a row for the companies asking, the metros hiring, the published pay, the
skills that appear alongside it, and the live openings.

### 3. Emerging terms

The ticker can only count skills it already knows. This does the opposite: it
reads every posting, finds **named technologies** that were barely mentioned a
few months ago, and ranks them by how fast they climbed.

It works by capitalisation. "PyTorch", "Karpenter" and "CrowdStrike" are
capitalised mid-sentence; "understands" and "great place" are not. A term also
has to appear at three or more different companies, otherwise one employer's
house style looks exactly like a market trend.

### 4. Sectors

The same questions asked per industry — AI, fintech, healthcare, security,
gaming, aerospace and the rest. How many early-career roles each one has, how
that is changing, what it pays, and which companies are hiring.

The useful column is **lift**. Terraform being common everywhere is not news;
Terraform being three times as common in one sector is. Healthcare, for example,
currently asks for Java at 3.5× the market rate and PostgreSQL at 3.8× — so
someone aiming at health tech should learn different things from someone aiming
at AI infrastructure.

Sector comes from `data/companies.yml`, where each company is labelled by hand.
Anything unlabelled is guessed from the job description, and only committed to
when several sector-specific words appear — one passing mention of "payments"
is not enough to call a company fintech.

### 5. Where the jobs are

A choropleth map of the United States shaded by volume, plus postings by metro,
published pay by metro as range bars, the remote share over time, and which
companies are opening more early-career roles versus which have gone quiet.

**About the map.** The boundaries come from
[us-atlas](https://github.com/topojson/us-atlas) (ISC licensed, built from US
Census Bureau cartographic files, which are public domain), in the Albers USA
projection — the standard for US thematic maps, with Alaska and Hawaii placed
as insets so the lower 48 stay legible.

There is no mapping library at runtime. `scripts/build_us_map.py` converts the
TopoJSON into finished SVG paths once, and the dashboard draws them directly.
The map never changes, so there is no reason to ship a projection engine to the
browser and re-run it on every page load — and it keeps the page working
offline with no CDN.

To rebuild it:

```bash
curl -sSL -o var/tmp/states-albers-10m.json https://cdn.jsdelivr.net/npm/us-atlas@3/states-albers-10m.json
.venv/Scripts/python scripts/build_us_map.py
```

Nine small north-eastern states — Vermont through DC — are labelled with leader
lines out to the right, because they are too narrow to hold text. Without that
they end up either unlabelled or buried under overlapping type, which is how
most US choropleths go wrong.

**On "where talent is moving":** this measures where the *jobs* are, not where
individual people went. That data lives on LinkedIn and getting it would mean
scraping profiles, which this project does not do. Company hiring is public and
countable, and for someone deciding which city to target it is the more useful
number anyway. The map also states how many roles it is leaving out — anything
advertised as remote or US-wide belongs to no single state.

### 6. What companies are trying to solve

Job descriptions state the problem outright — "you will build X because Y does
not scale". Claude reads the relevant passages and writes up the recurring
themes in plain English. Every theme cites the postings it came from, so
nothing is invented.

---

## Other roles

The scope is set by a **profile**, not hardcoded. Two ship with the project:

```bash
.venv/Scripts/python -m tt ticker                      # software engineering
TT_PROFILE=product .venv/Scripts/python -m tt ticker   # product management
```

A profile is one YAML file in `data/profiles/` that says four things: which
titles count, which titles to exclude, how many years is still early career,
and what to type into the search box on boards that will not list everything.
It can also name extra skill dictionaries from `data/skills/`.

Everything else is role-agnostic and shared. Reading job boards, parsing
locations and pay, detecting visa sponsorship, grouping by sector, the map, the
alerts, the charts — none of it knows or cares what kind of job a posting is
for.

**Each profile gets its own database** (`var/talentticker-product.db`).
`eligible` means something different for each one, and a single shared table
would mean every query carrying a profile filter, with one missed filter
quietly mixing product roles into the engineering figures.

### Fetching, when more than one profile is running

Two profiles against the same registry would send identical requests to the
four readers that list a whole board and filter locally. Measured across an
engineering and a product run, that was 237 boards pulled twice and 188 MB
re-downloaded for no benefit to anyone, least of all the companies serving it.

So those four - Greenhouse, Ashby, Lever, Amazon - write to a shared fetch
cache in `var/fetchcache.db`, and a second profile within the next three hours
reads from it instead of the network. Workday and Eightfold are **not** cached:
they search by title, so their answers genuinely depend on the profile, and
serving a product run the results of a software search would be wrong.

The saving is lopsided and worth understanding: about **4% of the requests but
91% of the bytes**. Workday makes thousands of tiny per-job calls that cannot
be shared; the four bulk readers are a handful of requests carrying nearly all
the traffic.

`TT_FETCH_CACHE_MINUTES=0` turns it off. A nightly refresh always goes out for
real, since the window is shorter than a day.

### Adding a role

Copy `data/profiles/product.yml`, change the title lists, and run:

```bash
TT_PROFILE=design .venv/Scripts/python -m tt setup
TT_PROFILE=design .venv/Scripts/python -m tt refresh
TT_PROFILE=design .venv/Scripts/python -m tt serve --port 8078
```

Two things are worth knowing before you write one, because both caused real
bugs when product management was added:

- **"Manager" may be the job rather than a rank.** Engineering treats any
  manager title as out of range; for product it is the job title itself. The
  classifier detects this by checking whether the profile's own title terms
  contain "manager", and switches the rule off when they do — while still
  excluding directors and VPs, which are senior under any profile.
- **Experience is phrased differently outside engineering.** "1–3 years in a
  product role" contains none of the words the engineering parser looked for,
  so the requirement went unread and mid-level jobs were kept as though they
  had stated nothing.

---

## Reading the dashboard

Every table sorts. Click a column heading to sort by it, click again to
reverse. Numeric columns start at "most" because that is usually the
interesting end. Rows on the ticker and the sector table open a detail panel.

Hovering a state tile, a pay bar or a point on any chart shows the exact
figures behind it.

---

## Getting started

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Copy the settings file and fill it in:

```bash
cp .env.example .env
```

You need to supply two things yourself:

- **`ANTHROPIC_API_KEY`** — for the "what they're solving" page. Everything
  else works without it.

  Each write-up is one Claude call over about forty postings, roughly **$0.17**.
  The market view rebuilds daily and the per-company ones weekly, which comes to
  around **$10 a month**. Running both nightly would be about $46, which is why
  it is split. Set `TT_THEME_COMPANIES=0` to skip the per-company write-ups, or
  raise it to cover more employers. Check the cost of any run before paying for
  it with `python -m tt themes --dry-run`.

  One gotcha worth knowing: some tooling sets `ANTHROPIC_BASE_URL` to a local
  proxy, and the SDK reads that variable automatically. This project pins the
  endpoint itself, so a stray value cannot silently redirect your requests.
  Override deliberately with `TT_ANTHROPIC_BASE_URL` if you need to.
- **SMTP details** — for email alerts. With Gmail, create an App Password
  (Google Account → Security → 2-Step Verification → App passwords). Your
  normal password will not work. Set `TT_SMTP_DRY_RUN=1` while you tune your
  watchlists and alerts print to the console instead of being sent.

Then load the data. The first pull takes about a minute:

```bash
.venv/Scripts/python -m tt setup
.venv/Scripts/python -m tt refresh
.venv/Scripts/python -m tt serve
```

Open http://127.0.0.1:8000.

---

## Commands

| Command | What it does |
|---|---|
| `python -m tt setup` | Create the database, load the company list |
| `python -m tt refresh` | Full pull of every board. Run nightly |
| `python -m tt poll` | Check for brand-new jobs and send alerts |
| `python -m tt snapshot` | Record today's open counts |
| `python -m tt ticker` | Print the top skills to the terminal |
| `python -m tt emerging` | Rising terms not yet in the skill list |
| `python -m tt metros` | Where the jobs are |
| `python -m tt sectors` | Early-career roles by industry |
| `python -m tt sponsorship` | Who sponsors a work visa, and who says they will not |
| `python -m tt discover` | Find company boards we are not reading yet |
| `python -m tt themes --dry-run` | Show the Claude prompt and cost without spending anything |
| `python -m tt themes` | Ask Claude what companies are solving |
| `python -m tt reprocess` | Re-run the filters over stored postings, no re-fetching |
| `python -m tt serve` | Dashboard plus the background scheduler |

---

## The scheduler

`serve` starts these automatically:

| Job | When | What |
|---|---|---|
| `poll_hot` | every 5 min | New jobs at priority companies, then alerts |
| `poll_all` | every 60 min | The same across every company |
| `refresh` | daily | Full re-read, close vanished jobs, snapshot |
| `themes_market` | daily | Claude write-up of the whole market (~$0.17 a run) |
| `themes_companies` | weekly, Mondays | The same per employer, for the top 8 |
| `discover` | weekly | Retry boards that failed |

Set `TT_SCHEDULER=0` to turn it off and drive the same jobs from cron or Windows
Task Scheduler instead — every one of them is also a CLI command.

---

## How the 0–4 years filter works

This is the decision everything else rests on, so it is designed to be
auditable. Every posting is stored with a `reason` column explaining the call:

```sql
SELECT title, reason FROM postings WHERE eligible = 0 LIMIT 20;
```

A role is kept when it is software engineering **and** early career.

**Is it software?** Matched against a list of engineering titles, with an
explicit exclusion list for things that contain "engineer" but are not software
jobs — sales engineer, mechanical engineer, solutions engineer.

**Is it early career?** In order:

1. Management and executive titles are always out, whatever years they mention.
2. Senior individual-contributor wording is out, *unless* the description asks
   for four years or fewer — a "Senior Engineer, 3+ years" is reachable.
3. Years stated in the text decide it. The smallest number wins, since that is
   the real bar. "5 weeks of vacation" is not read as five years.
4. Level codes past the second rung (III, L5, SDE III) are out.
5. Early-career wording in the title — new grad, junior, associate, Engineer I —
   is enough on its own.
6. If nothing is stated, two backstops catch senior roles that name neither a
   seniority word nor a number: a required doctorate, and a base salary floor
   above $250,000.
7. Otherwise it is kept, flagged as low confidence.

---

## A caveat worth understanding

Reading a job board only ever shows jobs that are **still open**. A role posted
in March and filled in April has vanished. Greenhouse stamps every posting with
its original publish date, which gives useful history on the very first run, but
that history systematically undercounts older months.

Two things follow:

- **Trends are measured on share, not raw counts.** Share is much less affected,
  because both the skill count and the total shrink together.
- **`snapshots` builds real history from scratch.** Every day the scheduler
  records what was open. After a few weeks that table, not the backfill, is the
  trustworthy series.

Treat the twelve-month charts as directional. The 30-day comparison is solid.

---

## Layout

```
tt/
  sources/     one reader per job board (Greenhouse, Ashby, Lever)
  extract/     skills, years of experience, location, pay, boilerplate removal
  analytics/   the ticker maths, geography, emerging terms, Claude write-ups
  alerts/      watchlists and email
  web/         FastAPI routes and the dashboard
  ingest.py    fetch, interpret, store
  scheduler.py background jobs
data/
  companies.yml   which boards to read; add to it freely
```

SQLite, one file, no server. Dead boards deactivate themselves, so guessing at a
company token in `companies.yml` costs nothing.

## Tests

```bash
.venv/Scripts/python -m pytest tests -q
```
