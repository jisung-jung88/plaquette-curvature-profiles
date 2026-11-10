# Repository Instructions

## Start from the research record

Before research work, read `docs/research_memory/STATUS.md`, then use
`docs/research_memory/INDEX.md` or `python3 scripts/research_memory.py search <terms>`
to find relevant attempts and original evidence. Read conditions, observations,
interpretation, limits and predecessor/follow-up links before reusing a result.
A literal keyword miss is not proof that related work does not exist.

Preserve original data, run metadata, configuration and source snapshots.
Catalog entries are derived navigation and interpretation, not replacement
evidence. State whether a question or motivation is historically recorded or
reconstructed later. Read original README claims together with the current
evidence limitations and later corrections.

## Shared assets and distinct attempts

The paired repositories are `jisung-jung88/kappa-profile` and
`jisung-jung88/plaquette-curvature-profiles`. Shared historical `KP-Rxxx` IDs
identify the same research assets in both catalogs. An explicit mirror is a
second storage location, not independent execution, replication or evidence.
Check actual bytes and run/job identifiers, times and conditions when deciding
whether records are duplicates, separate repeats or subsequent variants.
Identical configurations or output bytes alone do not establish the same
execution: deterministic independent runs can produce identical outputs.

Use `KAP-Rxxx` for newly originating kappa-profile records and `PLQ-Rxxx` for
newly originating plaquette-curvature-profiles records. Pick an unused number
in that namespace and preserve the ID if a record is copied elsewhere. Never
reuse an ID for a different question. Add mirrors only when the corresponding
same-ID record actually exists; a new local-only record starts with no mirrors.
The peer repository is not automatically synchronized or declared authoritative
merely because it is newer. Preserve known relationships and explicit unknowns.
New interpretations of a shared historical asset can originate in a separate
KAP/PLQ follow-up record. Do not imply the peer adopted that interpretation or
silently rewrite the original observation in both catalogs.

## Include recordkeeping in research completion

For authorized work that creates findings, investigations, designs, partial or
failed runs, diagnostics or changed interpretations, follow
`docs/research_memory/README.md` as part of task completion:

1. Preserve the question, reason, actual conditions, observations, errors,
   interpretation and limits in the existing report/run-metadata structure.
   Reuse an existing report instead of manually duplicating it.
2. Add or update a stable record in `docs/research_memory/records.json` with exact
   original evidence paths and hashes. Keep execution status, evidence level,
   scientific interpretation and approval status separate.
3. Link consequential follow-ups and corrections in both directions. Preserve
   original negative findings; distinguish an invalid observation, an analysis
   error, incomplete verification and a changed interpretation.
4. Update current navigation when actual state changes. Run `validate`,
   `render`, and `render --check` through `scripts/research_memory.py`; verify
   new source bytes/hashes and apply the existing checks relevant to the change.
   Check actual peer records for cross-repository changes; syntax validation
   does not verify remote pages or scientific claims.
5. Use the Git route authorized for the task. Include question, reason, change,
   conditions, observations, interpretation, evidence and follow-up in the commit
   body. Report record IDs, source pointers, publication state, checks and
   unfinished work in the completion response.

`historical_run_inventory.json` and `source_inventory.json` are dated
reconstruction snapshots. Future attempts normally reuse their original run
metadata/report and add a concise record with relationships; they do not require
hand-rewriting these large historical inventories. Correct a historical
inventory only when new evidence warrants it, preserving the reason and scope.

A meaningful attempt is the record unit. Commit and document counts are not
fixed. Source and catalog can share one commit using an exact Git blob hash,
explicit null commit/url and a note before the commit SHA exists. The read-only
`locate` command resolves exact local path/blob content. No extra commit merely
to fill a self-hash is required. Formatting and catalog administration need no
new research record unless they produce a substantive finding.

## Preserve actual execution provenance

An import/archive commit is not necessarily the commit that executed a run.
Keep unknown runtime commit, dirty state and unrecorded job outcomes explicit.
For new execution, preserve actual code/configuration and environment identity,
seed/backend/mapping/shots where applicable, run/job IDs and timestamps, status,
errors and result hashes. Preserve executed diffs or changed-file hashes when
the checkout is dirty. Investigation-only work needs no invented run ID.

If a job fails or stops after returning partial data, preserve those data and
the unfinished conditions. Completion of some jobs or existence of figure code
does not establish completion of a whole campaign or a scientific conclusion.
Postprocessing preserved results is distinct from running a new experiment.

Evidence from another repository carries its own repository, commit, path and
blob identity. `locate` reports foreign sources as unsearched rather than
claiming local identical bytes prove foreign provenance. Keep large artifacts
in their established storage with actual URI/version/hash manifests and the
scope of verification; a listed object or selected ZIP member is not a verified
whole archive. Preserve missing evidence as unknown.

## Scope and operational care

Record organization does not itself authorize QPU jobs, cloud resources,
paid execution or a new scientific campaign. Inspect an existing runner before
using it for validation; some runners may submit hardware jobs. Prefer bounded
offline source/data checks for documentation and catalog changes, and report
failed checks without weakening them. Do not expose credentials or commit
tokens, private keys, environments or caches.
Both repositories are public. Keep new inputs, manifests and reports free of
credentials and material that is not authorized for public disclosure.

When resuming an older session or branch, read current main's instructions and
STATUS, preserve ongoing changes and exact historical evidence, and bring the
recordkeeping workflow into the authorized working route. The catalog is
maintained during Codex task completion; no background collection or automatic
commit service is configured.
