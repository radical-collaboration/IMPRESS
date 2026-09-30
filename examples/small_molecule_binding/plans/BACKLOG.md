# Small-molecule binding — backlog tracker

Open work items for this example, newest evidence first. One line per item; details live in
the linked doc. Keep `Status` current and delete rows once the fix lands **and** a campaign
confirms it.

Source of most entries below: the 8-node / 32-pipeline campaign **job `22534628`**
(2026-09-29 23:23:40 → 2026-09-30 11:23:50, `State=TIMEOUT`, `Elapsed=12:00:10`).
Run artifacts archived at
`/work/hdd/bdyk/hooten1/impress-data-after-fixes/smb_8node/small_molecule_binding/`.

| # | Item | Severity | Status | Doc |
|---|---|---|---|---|
| 1 | `adaptive_decision()` blocked the event loop; uncached `_read_fasta_seq` made it O(ensemble) Lustre reads | **critical** | **fixed, unvalidated at scale** | [adaptive-callback-serialization](2026-09-30-adaptive-callback-serialization.md) |
| 2 | Dragon `flow.shutdown()` teardown hang — no watchdog, wall limit is the only backstop | high | open | [dragon-teardown-watchdog](2026-09-30-dragon-teardown-watchdog.md) |
| 3 | `fastrelax` passes only 58% — the real scientific bottleneck, 510 failures / 833 backbone escalations | medium | open, needs decision | [fastrelax-pass-rate](2026-09-30-fastrelax-pass-rate.md) |
| 4 | `fold_min_ligand_iptm` gate is disabled; data supports enabling at 0.7 | low | open, needs decision | [ligand-iptm-gate](2026-09-30-ligand-iptm-gate.md) |
| 5 | `README.md` still documents `IMPRESS_TEST_MODE` and the `PROD`/`TEST` pair, both removed by PR #64 | low | open | — (doc-only; noted in CLAUDE.md 2026-09-28 row) |

## Item 1 status detail

Fixed on branch `scaling-wide`:

- `small_molecule_binding.py` — `_read_fasta_seq` memoised (`_FASTA_SEQ_CACHE`);
  `_parse_pdb_ca_coords` `lru_cache` raised 512 → 4096.
- `run_small_molecule_binding.py` — `adaptive_decision()` split into an `async` wrapper that
  `await asyncio.to_thread(...)`s a synchronous `_adaptive_decision_sync()` body.

Validated offline: 12/12 adaptive branch cases produce identical `(next_step, seq_retry_count,
rfd3_input_pdb)` cached vs uncached; the event loop now ticks during a cold 1200-entry decision
(it did not before). **Not yet validated at scale** — needs the acceptance test in the doc.

## Conventions

- Cite the job ID and the archived artifact path for every claim, the way the CLAUDE.md
  revision-history rows do. A finding without a job number behind it does not belong here.
- "needs decision" means the data is in hand and a human has to pick a threshold — do not
  silently change a gate that alters which designs pass.
