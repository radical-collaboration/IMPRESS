# Bio-databases: RCSB PDB, UniProt, AlphaFold DB, ESM Atlas, ColabFold MSA server

**One-line identity.** Five public HTTPS APIs the agent will call directly instead of staging their underlying
databases locally — structure lookup (RCSB), sequence/annotation lookup (UniProt), precomputed-structure lookup
(AlphaFold DB, ESM Atlas), and remote MSA generation (ColabFold MSA server) — all pattern **P5**, and all
shared, rate-limited, third-party-operated services an unattended campaign can genuinely overwhelm.

## Identity
- **Version / release examined:** no refcode in `impress-a-refcodes/` for any of the five — none is a tool this
  project vendors or builds; all are called over the network at whatever version the operator currently runs.
  One piece of *executable* evidence exists in-repo: `<workspace>/impress-a-refcodes/tools/boltz/src/boltz/data/msa/mmseqs2.py`
  is Boltz's actual client for `api.colabfold.com` (attributed in its own header comment to
  `https://github.com/sokrypton/ColabFold/blob/main/colabfold/colabfold.py`) — read in full and cited below,
  since it is the only place in this toolkit sweep where a real client's retry/backoff behavior against one of
  these services can be verified rather than inferred from docs.
- **Provenance:** RCSB PDB — wwPDB member, Rutgers/UCSD/legacy partners, US-government/NSF/DOE/NIH-funded, free
  and open. UniProt — UniProt Consortium (EBI + SIB + PIR), free and open, no login required. AlphaFold DB —
  EMBL-EBI hosting Google DeepMind-produced predictions, CC-BY-4.0 data license (same license as AF2 parameters
  per `alphafold.md`). ESM Atlas — Meta/EvolutionaryScale (`facebookresearch/esm`), free academic resource.
  ColabFold MSA server — Sergey Ovchinnikov / Milot Mirdita, hosted (per ColabFold's own MsaServer docs) at
  `api.colabfold.com`, explicitly described as a shared academic resource, not a commercial SLA-backed service.
- **Maturity:** production for all five, but with materially different operational postures: RCSB and UniProt
  are large-institution infrastructure with formal (if loosely quantified) usage guidance; AlphaFold DB is
  actively evolving its schema (see Failure modes — a real breaking-change deprecation is mid-flight as of this
  writing); ESM Atlas is a research-lab resource with no published SLA at all; the ColabFold MSA server is
  explicitly self-described as "a free and limited academic resource," the least production-hardened of the
  five and the one this project depends on most heavily.

## Scientific role
All five sit in the **search / generate-input / analyze** stages, not generate/score, and all four in-scope
problem classes (stability, de novo binder design, enzyme/catalytic design, small-molecule binding) touch at
least one of them at some point in a campaign:
- **RCSB PDB** — experimental structure lookup and metadata search: precedent-checking a target, pulling a
  starting scaffold, retrieving ligand/cofactor geometry for an enzyme-design or small-molecule task.
- **UniProt** — canonical sequence, annotation (active site, binding site, PTM, domain), and cross-database ID
  resolution (PDB ↔ UniProt ↔ Pfam ↔ GO ↔ AlphaFold DB entry, etc.) — the connective tissue between every other
  tool in this toolkit that identifies a protein by a different ID scheme.
- **AlphaFold DB** — precomputed AF2 structure lookup by UniProt accession, avoiding a from-scratch fold for any
  sequence already in Swiss-Prot/UniProt coverage.
- **ESM Atlas** — precomputed ESMFold structure lookup over ~772M metagenomic sequences, plus (per its own
  scripts) a live single-sequence fold-on-demand endpoint and per-sequence ESM2 embedding retrieval.
- **ColabFold MSA server** — the MSA-generation backend other Core tools in this toolkit call directly: Boltz's
  `--use_msa_server` (`boltz/docs/prediction.md:167-168`, default `--msa_server_url https://api.colabfold.com`)
  and Chai-1's `--use-msa-server` both depend on this exact service (see `boltz.md`, `chai.md`,
  `mmseqs2.md`). This is the one entry in this brief that is not an optional convenience — several Core tools'
  documented default invocation path fails without it or a substitute.

## Compute pattern (all five)
- **Pattern:** **P5** — network call over HTTPS, per taxonomy rule 5 ("egress-dependent tools are P5 even when
  they have a local fallback"). No local resource cost per call; the failure surface is latency, quota, rate
  limit, and outage rather than compute (`compute-pattern-taxonomy.md` row P5).
- **GPU vendor portability:** n/a — nothing runs on the agent's own allocation.
- **State model:** stateless per request (RCSB, UniProt entry/search, AlphaFold DB, ESM Atlas embedding lookup);
  **async job-queue** for two specific sub-services that must be polled rather than called once: UniProt ID
  mapping (`idmapping/run` → `idmapping/status/{jobId}` → `idmapping/results/{jobId}`) and the ColabFold MSA
  server (`ticket/msa` or `ticket/pair` → poll `ticket/{ID}` → `result/download/{ID}`, verified against
  `boltz/src/boltz/data/msa/mmseqs2.py:33,106-133`). Both job-queue patterns need the same durable-poll handling
  P4 tools need, even though the work itself is P5.
- **Data locality:** self-contained — the entire reason this brief exists is that these calls let the agent
  avoid shared-FS-required local database staging (see per-entry sizing below).
- **Staging burden:** none per call; see each entry for what local staging is specifically avoided.
- **Container availability:** n/a.

## Invocation & I/O contract (per-service)

### RCSB PDB — Search API + Data API
- **Endpoints:** Search API `https://search.rcsb.org/rcsbsearch/v2/query` (GET or POST, JSON query DSL,
  returns only identifiers — "If you need to extract information on released date, macromolecules, organisms,
  resolution, modified residues, ligands etc., you should use RCSB Data API," per `search.rcsb.org`'s own
  landing page). Data API `https://data.rcsb.org` (REST + GraphQL, full entry/entity metadata).
- **Auth:** none. No API key, no login, for either API.
- **Rate limits:** no published numeric ceiling for either API. RCSB's own guidance (`rcsb.org/docs/programmatic-access/web-apis-overview`):
  "We recommend starting with a handful of requests per second. If you exceed the limit, the service will
  respond with a 429 HTTP error code" — an empirical, not contractual, limit, discovered by getting throttled.
  Search API pagination caps at 10,000 hits per paginated request (`search.rcsb.org`). Data API batch/graph
  endpoints cap at 1,000 IDs per batch call. Shared-IP callers (university networks, VPNs, and — relevant here —
  a shared HPC center's outbound NAT) can hit the empirical ceiling sooner than an individually-metered caller
  because the throttle is IP-based, not credential-based.
- **What an agent would realistically ask:** "give me the deposited structure(s) for ligand X / organism Y
  matching these sequence or structure criteria" (Search API), then "give me resolution, deposited ligands,
  polymer entities, and experimental method for hit Z" (Data API) — the two-step precedent-check pattern that
  feeds Foldseek's and MMseqs2's own precedent-search stage (`foldseek.md`, `mmseqs2.md`) with metadata those
  tools don't themselves carry.
- **What local staging this avoids:** the full PDB mirror (mmCIF, all current entries) is on the order of
  tens of GB compressed / >100 GB uncompressed and requires a scheduled local rsync/refresh to stay current;
  routine per-target lookups make that staging unnecessary for anything short of a bulk structural-genomics-scale
  campaign.

### UniProt — REST API + ID mapping
- **Endpoints:** `https://rest.uniprot.org/uniprotkb/{accession}` (single-entry retrieval, content-negotiated
  or `.json`/`.fasta`/`.txt` suffix), `https://rest.uniprot.org/uniprotkb/search?query=...` (search), and the
  asynchronous ID mapping service: `POST rest.uniprot.org/idmapping/run` (submit `ids`/`from`/`to`) →
  `GET rest.uniprot.org/idmapping/status/{jobId}` (poll) → `GET rest.uniprot.org/idmapping/results/{jobId}`
  (paginated results) — the same submit/poll/retrieve shape as the ColabFold MSA server below, not a
  coincidence (both are queue-backed bulk services sitting behind a synchronous-looking REST front door).
- **Auth:** none. No API key required for any of the above.
- **Rate limits:** no formally published numeric ceiling; UniProt throttles excessive request rates and
  returns HTTP 429 with a `Retry-After` header that a well-behaved client should honor rather than guess at a
  backoff interval. **ID mapping specifically** has documented hard limits independent of request rate: a
  single job accepts a **maximum of 100,000 IDs**, and job results are retained server-side for a **maximum of
  7 days** before the job must be resubmitted — an autonomous agent running a long campaign must not treat a
  submitted ID-mapping job as a durable store; it must fetch and persist results locally well inside that
  7-day window.
- **What an agent would realistically ask:** "resolve this PDB chain / RCSB entry / Foldseek hit back to a
  canonical UniProt accession and its annotated active-site/binding-site/domain residues" — the annotation
  layer no structure-only tool in this toolkit provides on its own, and the ID-resolution hub connecting RCSB,
  AlphaFold DB, and Pfam/GO references that arrive at the agent from different tools under different ID schemes.
- **What local staging this avoids:** UniProtKB (Swiss-Prot + TrEMBL) is hundreds of GB even compressed and
  changes on every release cycle; per-accession or per-batch lookups avoid staging and, critically, avoid the
  version-drift problem of a locally frozen snapshot silently going stale mid-campaign.

### AlphaFold DB — prediction lookup API
- **Endpoint:** `GET https://alphafold.ebi.ac.uk/api/prediction/{uniprot_accession}` — returns a JSON summary
  (confidence fractions, model version/date, and direct download URLs for `.pdb`/`.cif`/`.bcif`).
- **Auth:** none.
- **Rate limits:** no numeric ceiling independently confirmed in this pass; EMBL-EBI (AlphaFold DB's host)
  publishes per-service throttles elsewhere in its portfolio (e.g. 5 requests/second is the documented ceiling
  for its Variant Region API) that are illustrative of EBI's general fair-use posture but were **not** found
  stated specifically for the AlphaFold DB prediction endpoint — treat any assumed number as inferred, not
  confirmed, and default to conservative client-side throttling (single-digit requests/second, serial rather
  than parallel bursts) absent a published figure.
- **Outage / instability as a first-class risk, not a footnote:** EMBL-EBI's own AFDB news page
  ("Breaking changes to the AFDB predictions API," `ebi.ac.uk/pdbe/news/breaking-changes-afdb-predictions-api`)
  documents a live schema migration — field renames (`entryId`→`modelEntityId`, `uniprotStart`→`sequenceStart`,
  `uniprotEnd`→`sequenceEnd`, `uniprotSequence`→`sequence`, `isReviewed`→`isUniProtReviewed`,
  `isReferenceProteome`→`isUniProtReferenceProteome`) and an outright field **removal** (`paeImageUrl`, PAE
  images no longer served), run on a 9-month dual-support window with a stated **sunset date of 2026-06-25**.
  As of this brief's writing (2026-09-21) that sunset date has already passed — meaning an agent client hard-coded
  against the old field names may already be silently receiving `null`/missing fields today, not at some future
  date. **This is the single most concrete, dated instance of API instability found anywhere in this sweep**,
  and it is a template for how these services fail: not primarily by going down, but by changing shape under a
  caller that doesn't defensively check for field presence.
- **What an agent would realistically ask:** "has this UniProt accession already been folded by AF2, and at
  what confidence" — the single-lookup precedent check upstream of ever spending a GPU-hour on a fresh
  structure prediction for a sequence AlphaFold DB already covers (currently covering the majority of
  Swiss-Prot plus 46 reference proteomes, per its own bulk-download page).
- **What local staging this avoids:** the AlphaFold DB bulk Swiss-Prot-coverage tarball set is on the order of
  low-hundreds-of-GB; per-accession lookups avoid that entirely for anything short of a whole-proteome sweep.

### ESM Atlas — fold, search, embedding lookup
- **Endpoints (from `facebookresearch/esm`'s own `scripts/atlas/README.md`):** `POST
  https://api.esmatlas.com/foldSequence/v1/pdb/` (raw sequence in the request body, no auth, **≤400 residues**
  per call — this is a live ESMFold inference call, not a lookup, and is the one entry in this brief that is
  compute-shaped rather than pure lookup); `GET https://api.esmatlas.com/fetchEmbedding/ESM2/{id}` (per-sequence
  ESM2 embedding retrieval by Atlas ID); plus a documented but less-specified structure/sequence search over a
  subset of the ~772M-sequence Atlas.
- **Auth:** none for any of the above.
- **Rate limits:** no officially published numeric ceiling found; a standing, still-open community question
  (`facebookresearch/esm` GitHub Issue #375, "ESMAtlas api access: Rate limit?") indicates this has never been
  authoritatively answered by the operators even to their own user community — treat this service as the
  **least contractually documented** of the five, and budget accordingly (serial calls, generous backoff, no
  assumption of sustained throughput).
- **What an agent would realistically ask:** "has this near-novel sequence already been folded somewhere in the
  metagenomic Atlas" (embedding/search lookup) or, for a short design candidate under 400 residues, "fold this
  sequence now without spending a local GPU-hour" (the `foldSequence` endpoint) — genuinely useful as a
  zero-cost sanity-check fold for small designs before committing local ESMFold/Boltz/Chai compute, but not a
  substitute for local inference on anything longer than 400 residues or anything needing PAE/multimer support.
- **What local staging this avoids:** the full Atlas bulk data is enormous — metadata alone ~25 GB
  (SQLite/Parquet), high-confidence-structure tarballs ~1 TB, the full structure set ~15 TB, plus separate
  Foldseek-index and ESM2-embedding bulk downloads — an agent doing occasional precedent lookups should never
  attempt to mirror this; the operators' own guidance is to use `aria2c`/`s5cmd` against the prepackaged
  tarballs (not per-file API loops) for anyone who does need bulk access, which is itself a data point about
  what this API is and isn't meant for: individual lookups, not scraping.

### ColabFold MSA server — MSA generation-as-a-service
- **Endpoints, verified against Boltz's actual client** (`boltz/src/boltz/data/msa/mmseqs2.py:33,65-158`):
  `POST {host_url}/ticket/msa` (single-sequence MSA) or `POST {host_url}/ticket/pair` (paired/complex MSA),
  body `{q: <fasta-formatted query>, mode: <env|all|env-nofilter|nofilter|pairgreedy|paircomplete...>}`,
  default `host_url = https://api.colabfold.com`; `GET {host}/ticket/{ID}` to poll job status; `GET
  {host}/result/download/{ID}` to fetch the resulting `.a3m` tarball. Boltz's client reads a `status` field
  with the values `UNKNOWN`, `RATELIMIT`, `PENDING`, `RUNNING`, `COMPLETE`, `ERROR`, `MAINTENANCE` — i.e. **the
  server's own protocol has a first-class `RATELIMIT` status**, not just an HTTP 429; a well-behaved client
  must check this field, not just the HTTP status code.
- **Auth:** none for the public server by default. Boltz's client (and, by the same infrastructure, Chai's)
  additionally supports HTTP Basic auth (`msa_server_username`/`msa_server_password`) or header-based API-key
  auth (`auth_headers`, e.g. `X-API-Key`) for callers pointed at an authenticated **self-hosted or paid**
  instance — this is the concrete mechanism by which "use the paid/bulk route" is actually implementable, not
  a hypothetical.
- **Rate limits — the load-bearing fact in this brief:** the public server is explicitly self-described (per
  ColabFold's own documentation and FAQ, cross-checked via `sokrypton/ColabFold` on GitHub) as **"a free and
  limited academic resource"** capable of processing on the order of a **few thousand MSAs per day** in
  aggregate across every user worldwide — not per-caller, aggregate. The ColabFold FAQ states verbatim: *"You
  can access the server from a local computer if your queries are serial from a single IP. Please do not use
  multiple computers to query the server."* The server enforces this with its own `RATELIMIT` status (above)
  and reserves the right to restrict access case-by-case when a caller exceeds fair use.
- **Boltz's own retry/backoff behavior, verified line-by-line (`mmseqs2.py:71-97,106-133,197-251`):** on
  `RATELIMIT` or `UNKNOWN` status the client sleeps `5 + random(0, 5)` seconds and resubmits, indefinitely (no
  cap on ratelimit-triggered retries — a real gap, see below); on transport-level exceptions (timeouts,
  connection errors) it retries up to 5 times with a flat 5-second sleep before raising; on `RUNNING`/`PENDING`
  it polls every `5 + random(0, 5)` seconds; on `ERROR` it raises immediately with "please try again an hour
  later"; on `MAINTENANCE` it raises immediately. **This is the reference implementation this project should
  match or improve on**, and it has a real weakness worth flagging: the `RATELIMIT`/`UNKNOWN` resubmit loop has
  no maximum retry count and no exponential growth — an unattended agent inheriting this exact logic during a
  sustained server-side rate-limit event will spin indefinitely at a near-constant ~5-10s cadence, which is
  itself contrary to good fair-use citizenship even though each individual retry is small.
- **Outage is a multi-tool failure mode, not a single-tool one:** because Boltz's `--use_msa_server` and
  Chai's `--use-msa-server` both default to this exact service (`boltz.md`, `chai.md`), a `MAINTENANCE` window
  or sustained fair-use throttling at `api.colabfold.com` silently degrades every Core folding tool in this
  toolkit that was configured to lean on it, simultaneously, not just one. An agent that only checks "did
  Boltz's job fail" without attributing the failure to the shared MSA dependency will misdiagnose a
  single-point-of-failure outage as N independent tool failures.
- **Fallback, concretely:**
  1. **Local MMseqs2 search** against staged UniRef30 + ColabFoldDB (`mmseqs2.md`'s own recommendation) —
     requires the databases resident (per ColabFold's self-hosting docs, **768–1024 GB RAM** to keep
     UniRef30+ColabFoldDB resident for a self-hosted `mmseqs2-server` instance) — a heavy but real fallback,
     appropriate for a site that already runs large-batch campaigns and would otherwise routinely strain the
     public server's fair-use ceiling.
  2. **Self-hosted or third-party-paid MSA server** pointed at via `--msa_server_url` (Boltz) — the officially
     supported escape hatch (`prediction.md:168`, plus the auth mechanisms above), including third-party
     hosted offerings (e.g. commercial co-folding platforms have begun offering their own hosted MSA servers as
     a direct response to public-server reliability incidents — worth a targeted look if this becomes a
     recurring operational pain point, not independently vetted in this pass).
  3. **Cached/precomputed MSAs** — Boltz accepts a pre-computed `.a3m` path directly (`prediction.md`), so an
     agent that has already generated an MSA for a sequence (via any of the above) should persist and reuse it
     rather than re-querying the public server for a sequence it has seen before — the single cheapest fair-use
     improvement available and the one most directly under this project's own control.
- **What an agent would realistically ask:** "generate an MSA for this designed or query sequence so a
  co-folding model can run" — this is not an optional convenience call, it is the documented default MSA path
  for two Core tools in this toolkit.
- **What local staging this avoids:** UniRef30 (~52.5 GB download / ~206 GB uncompressed) + ColabFoldDB/BFD-class
  metagenomic DB (order of hundreds of GB to ~1.8 TB uncompressed depending on which bundle) — figures carried
  over from `mmseqs2.md`'s own staging table, the same underlying databases.

## Acceptable-use posture: is unattended, high-volume automated use of these services legitimate?

**RCSB and UniProt:** yes, with ordinary courtesy. Both are large, professionally operated public-data
infrastructure explicitly designed for programmatic access (both publish REST/GraphQL APIs specifically for
this purpose), neither publishes a hard numeric ceiling, and both signal overload via a standard HTTP 429 with
(for UniProt) a `Retry-After` header. An autonomous campaign issuing hundreds to low-thousands of lookups over
a multi-day run is squarely within normal use for these two, provided the agent (a) respects 429/`Retry-After`
with real exponential backoff rather than tight-loop retry, (b) caches results client-side rather than
re-fetching the same accession/entry repeatedly within a campaign, and (c) uses batch endpoints (RCSB Data API's
1,000-ID batch, UniProt's ID-mapping job queue up to 100,000 IDs) instead of one-row-at-a-time loops whenever the
workload is genuinely bulk.

**AlphaFold DB and ESM Atlas:** yes for individual precedent-lookup traffic (the intended use), but an agent
must not treat either as a substitute for its own documented bulk-download path. Both operators explicitly
provide prepackaged bulk tarballs precisely so that scripted per-accession/per-ID API loops don't have to
substitute for a real mirror — hammering either API with a loop over tens of thousands of accessions when a
bulk tarball exists for the same data is the wrong tool for that job, not just discourteous. Individual,
occasional lookups triggered by the agent's own design loop (checking one candidate at a time) are the
service's intended use case and are fine unthrottled-by-policy, though client-side throttling to single-digit
requests/second is the prudent default given neither publishes a numeric ceiling.

**The ColabFold MSA server is the one service in this brief where unattended, high-volume use is genuinely in
tension with the operators' stated intent**, and deserves a direct, concrete recommendation rather than a
generic "be polite" note:
- The server is **explicitly not sized for automated agent traffic at any real scale** — "a few thousand MSAs
  per day" aggregate, shared across every academic user of ColabFold worldwide, is a capacity an unattended
  multi-day autonomous design campaign generating hundreds of candidate sequences per iteration can meaningfully
  dent on its own.
- **Concrete recommendation:** treat the public `api.colabfold.com` server as the **interactive/low-throughput
  default only** — single-digit-to-tens of MSA requests per campaign iteration, always cache-checked against a
  local store of already-generated MSAs first (item 3 above), always with capped, truly exponential backoff on
  `RATELIMIT`/`MAINTENANCE` (improving on Boltz's own uncapped linear-jitter retry loop, not just copying it).
  **Any campaign whose design suggests it will need more than roughly a few dozen distinct-sequence MSAs per
  day should default to local MMseqs2 search or a self-hosted/paid MSA server from the start**, not discover
  the public server's ceiling by getting rate-limited mid-campaign. This is a capacity-planning decision that
  belongs in the campaign's own resource plan, not something to leave to reactive backoff logic alone.
- Because this server is silently load-bearing for two separate Core tools (Boltz, Chai), the agent's own
  health-check/monitoring layer should treat `api.colabfold.com` reachability as a named, first-class dependency
  to check at campaign start, not an implementation detail buried inside each tool's own error path.

## Deployment on DOE & ACCESS
Nothing is installed and nothing runs on the allocation, so "deployment" here means exactly one thing:
**does the compute node have outbound HTTPS?** This project's stated platform assumption is full egress
(`compute-pattern-taxonomy.md`), which makes all five services directly callable from inside a job on
Frontier, Aurora, Polaris, Delta, Bridges-2, and Expanse alike. There is no GPU, module, or container
dimension to any of it.

That single assumption is load-bearing to an uncomfortable degree, and it is worth stating plainly what
its retraction would cost. Egress policy on leadership-class machines is a site decision that can change
without reference to this project, and it is frequently *partial* — a proxy env var, an allowlist, or
egress from login/DTN nodes but not compute nodes. If egress is withdrawn or restricted, this entire brief
converts from "five cheap network calls" into a multi-terabyte local staging problem: AF2-class genetic
databases (~2.6 TB), the ColabFold DB and UniRef30 for local MMseqs2 (768–1024 GB RAM resident, per
`mmseqs2.md`), plus local mirrors for PDB and UniProt. The mitigation is the same in every case and should
be built regardless of egress confidence: **cache every response on the shared filesystem, keyed by
request**, so a campaign re-run costs nothing and an outage degrades to a cache hit rather than a failure.

Self-hosting is the specific recommendation for the ColabFold MSA server, for availability control rather
than for egress: the public instance is a shared academic resource, and a campaign that depends on it for
two Core tools should not be discovering its limits under load.

## Agentic surface
- **Native MCP:** **yes, for RCSB PDB** — `github.com/rcsb/rcsb-mcp`, confirmed as an official RCSB
  organization repository via the GitHub API (see `mcp-landscape.md`). EMBL-EBI's PDBe likewise ships
  `PDBeurope/PDBe-MCP-Servers`, org-confirmed. These are the healthiest corner of the MCP ecosystem for
  this project: read-only lookups over stable public APIs, which is the use case MCP handles well.
- **Community MCP (unverified):** UniProt and AlphaFold DB servers exist from the `Augmented-Nature`
  organization, which is **independent and unaffiliated** with UniProt or EMBL-EBI despite naming that
  reads as official once a marketplace strips provenance. Treat as unverified third-party code; do not
  adopt into an unattended pipeline without review.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trades off |
|---|---|---|---|---|
| Result limit / page size | int | 10–1,000 (RCSB Data API batches at 1,000 IDs) | 100 | Coverage vs. response size and service load |
| Search stringency (E-value, identity cutoff) | float | task-dependent | service default | Recall vs. precision and payload size |
| ID-mapping batch size | int | ≤100,000 per job (UniProt hard cap) | 10,000 | Fewer, larger jobs vs. finer-grained restart granularity |
| MSA pairing strategy (ColabFold) | enum | `greedy` / `complete` | `greedy` | Complex-MSA quality vs. MSA build time |
| Cache TTL | duration | 1–90 days | 30 days | Freshness vs. request volume against public services |

- **Parameters that must NOT be agent-varied:** the **retry and concurrency policy**. Backoff floor,
  maximum retry count, and per-service concurrency cap must be fixed configuration, never something the
  agent can raise to "make progress." An autonomous loop that widens its own concurrency under rate
  limiting converts a transient throttle into sustained abuse of shared public infrastructure — and Boltz's
  own bundled client shows how easily this happens, retrying `RATELIMIT` in an uncapped `5+jitter` loop
  (`boltz/src/boltz/data/msa/mmseqs2.py`). That loop is a pattern to fix, not to inherit. Honouring
  `Retry-After` is likewise mandatory, not tunable.

## Failure modes & what the agent must check
- **Loud failure:** HTTP 429 (RCSB, UniProt, presumably AlphaFold DB/ESM Atlas though not independently
  confirmed for the latter two), malformed-input 4xx responses (e.g. an invalid UniProt accession, a
  >400-residue sequence to ESM Atlas's `foldSequence` endpoint), and the ColabFold server's own `ERROR`/
  `MAINTENANCE` status strings (raised as exceptions by Boltz's client, `mmseqs2.py:209-222,244-251`).
- **Silent bad output / degraded state:**
  - **AlphaFold DB schema drift** (documented above, sunset already passed as of this writing) — a client
    reading old field names may receive `None`/missing values that look like "no data" rather than "field
    renamed," silently degrading confidence-filtering logic downstream. **Check:** verify presence of both old
    and new field names defensively, or pin to a specific, tested response schema and fail loudly (not
    silently default) if expected fields are absent.
  - **ColabFold `RATELIMIT`/`UNKNOWN` uncapped retry** (above) — an agent that copies Boltz's exact retry loop
    verbatim inherits an indefinite-retry pattern with no maximum attempt count; over a long unattended
    campaign this can silently consume wall-clock time and API goodwill without ever surfacing as a distinct
    "MSA server unavailable" event the agent's own monitoring would catch. **Check:** wrap with an explicit
    max-retry/max-duration ceiling and escalate to the local-MMseqs2 fallback rather than retrying forever.
  - **Empty/near-empty search or lookup results indistinguishable from "genuinely novel"** — the same failure
    mode `foldseek.md`/`mmseqs2.md` name for local search tools applies here too: a zero-hit RCSB/UniProt/AFDB
    query can mean either "genuinely nothing exists" or "malformed query/wrong ID scheme/transient server
    issue." **Check:** run a known-positive control query (a well-known accession) through the same code path
    before trusting a null result inside a design-loop decision.

## Cost per unit of work
- RCSB Search + Data API call: sub-second to low-seconds, no local resource.
- UniProt single-entry lookup: sub-second; ID-mapping job (async): seconds to low-minutes depending on batch
  size (up to 100,000 IDs), requires polling.
- AlphaFold DB single-accession lookup: sub-second.
- ESM Atlas `foldSequence` call (≤400 residues): this is real remote GPU inference, not a lookup — wall-clock
  is comparable to a single local ESMFold call for a short sequence (seconds), but it is someone else's GPU
  budget, not the agent's own allocation; embedding fetch is sub-second.
- ColabFold MSA generation: Boltz's own client estimates ~150 seconds per unique sequence as a progress-bar
  baseline (`mmseqs2.py:195`, `TIME_ESTIMATE = 150 * len(seqs_unique)`) — this is the client's own rough
  estimate for UX purposes, not a guaranteed SLA, and real wall-clock varies with server load (this is exactly
  the shared-capacity risk this brief flags above).
- None of the five are checkpointable in the traditional sense; the two job-queue sub-services (UniProt ID
  mapping, ColabFold MSA) survive the agent's own process restart because the job lives server-side — the
  agent's own durable state only needs to remember the job/ticket ID to resume polling, not re-submit.

## Verdict
**Core (all five), with the ColabFold MSA server flagged as the operationally sensitive one.** RCSB, UniProt,
and AlphaFold DB are low-risk, well-provisioned public infrastructure an autonomous agent can lean on routinely
with ordinary courtesy (backoff, caching, batch endpoints). ESM Atlas is useful but the least contractually
documented — budget conservatively. The **ColabFold MSA server is Core by necessity, not by choice**: it is the
documented default MSA path for two other Core tools (Boltz, Chai), so this project cannot avoid depending on
it, but it is also explicitly sized as a shared academic resource, not agent-scale infrastructure — the
project's own resource plan should treat "local MMseqs2 fallback" and "self-hosted/paid MSA server" as
first-class deployment options to be provisioned proactively for any campaign expected to exceed light,
interactive-scale MSA demand, rather than as break-glass options discovered only after the public server starts
returning `RATELIMIT`.

## Sources
- `<workspace>/impress-a-refcodes/tools/boltz/src/boltz/data/msa/mmseqs2.py` (read in full;
  verified endpoints, status values, retry/backoff logic, auth mechanisms)
- `<workspace>/impress-a-refcodes/tools/boltz/docs/prediction.md` (verified: `--use_msa_server`,
  `--msa_server_url` default, `--msa_pairing_strategy`, authentication flag documentation lines 167-169, 254-287)
- `briefs/boltz.md`, `briefs/chai.md`, `briefs/mmseqs2.md`, `briefs/foldseek.md`, `briefs/alphafold.md` (this
  project's own briefs — cited for cross-references and the MMseqs2/AF2-family staging-size figures reused here)
- RCSB: https://www.rcsb.org/docs/programmatic-access/web-apis-overview ; https://search.rcsb.org/ ;
  https://data.rcsb.org/ ; https://data.rcsb.org/redoc/index.html (web-searched/fetched, not repo-verified)
- UniProt: https://www.uniprot.org/help/id_mapping ; https://www.uniprot.org/api-documentation ;
  https://rest.uniprot.org (web-searched, not repo-verified; the ~200 req/s figure surfaced in one secondary
  search summary is **not independently confirmed against a primary UniProt document** and is deliberately
  omitted from the body above as unverified — only the documented ID-mapping job limits (100,000 IDs / 7-day
  retention) and the general 429+Retry-After behavior are asserted as fact)
- AlphaFold DB: https://alphafold.ebi.ac.uk/api-docs ; example schema via secondary sources (x-cmd.com,
  Medium tutorial — cross-checked field names against the breaking-changes announcement below);
  https://www.ebi.ac.uk/pdbe/news/breaking-changes-afdb-predictions-api (fetched in full — source for the
  field-rename table and the 2026-06-25 sunset date)
- ESM Atlas: https://github.com/facebookresearch/esm/blob/main/scripts/atlas/README.md (fetched);
  https://github.com/facebookresearch/esm/issues/375 ("ESMAtlas api access: Rate limit?", cited as evidence the
  question has no public authoritative answer, not independently re-confirmed by opening the issue thread in full)
- ColabFold MSA server: https://github.com/sokrypton/ColabFold/blob/main/README.md (fetched — source for the
  single-IP-serial-queries FAQ quote); https://github.com/sokrypton/ColabFold/tree/main/MsaServer and
  `MsaServer/README.md` (fetched — source for self-hosting RAM figures and `server.ratelimit` config option);
  "free and limited academic resource... few thousand MSAs per day" and fair-use case-by-case restriction
  language reflects a secondary-source (search-engine) synthesis of ColabFold's own stated policy and is
  flagged as **paraphrased from search results, not a direct primary-document quote independently re-verified
  in this pass** — treat the exact wording as approximate, the substance (shared, capacity-limited, fair-use
  enforced) as reliable given it is corroborated by the FAQ quote and the `RATELIMIT` status Boltz's own client
  code explicitly handles.
