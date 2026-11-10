# Archived-data reuse verification — 2026-11-10

These summary tables were **regenerated on 2026-11-10** from the repository's
existing archived inputs using its six unchanged README figure commands.
They are current verification outputs, not original historical figure artifacts
and not new QPU or simulation acquisitions.

`manifest.json` records exact source/input hashes, both identical repository
snapshots, the Python/package environment, command templates, analysis settings,
exit codes and output hashes. All six commands succeeded. The 78 original
reproducibility files remained unchanged and the worktree was clean before/after.

| Figure | Retained high-level tables |
|---|---|
| 3 | Simulation summary: 30 rows; signal-control differences: 12 rows |
| 4 | Simulation profile panel statistics: 6 rows |
| 5 | Selected Day1 QPU summary: 27 rows; differences: 9 rows |
| 6 | Selected Day1 QPU profile panel statistics: 6 rows |
| 7 | Schedule-ablation summary: 16 rows, including pooled derivatives |
| 8 | Each selected day: 27 summary rows and 9 difference rows |

The explicit original day mappings were used: Day1 `(eta, run)` values
`(0,6), (0.1,8), (0.2,5)` and Day2 `(0,8), (0.1,9), (0.2,7)`.
Figure 8 was rendered for n=7. Original bootstrap settings were retained
(5,000 replicates where configured).

For Figure 7, I1–I4 are four interleaved acquisitions at 512 shots/circuit.
I12 and I34 pool pairs of those inputs, and I_sum pools all four into a
2,048-shot-per-circuit estimate. These three pooled products are **not new
independent runs**. The blocked acquisition has 2,048 shots/circuit.

The numeric tables support inspecting/reusing the original analysis path.
Their existence does not settle scientific interpretation or repair historical
provenance gaps. The raw point estimate and bootstrap-median point estimate are
separate fields in the original code; preserve that distinction when reading
values and intervals.

PDFs/PNGs, context-level tables, repeated Figure 7 cache copies and font caches
are omitted from this small bundle. The output manifest records their hashes.
Only repeated font-metadata timestamp warnings appeared on stderr; commands
returned success. No original historical rendered-output comparison was made.
