# Archived plans

Completed plans live here so that `planDocuments/` holds only what is being
worked on. **Being in this directory is what "done" means** — nothing here has
to be opened to check its status.

The history is kept rather than trimmed. Each step's detail is also in the
commit that landed it, so these documents are a record, not a reference.

| Plan | State when archived |
|---|---|
| `refactor_plan.md` | Complete 2026-09-10 — reviewed in [`post_refactor_review.md`](../post_refactor_review.md) |
| `session_and_traces_plan.md` | Complete 2026-09-10, with three exit criteria recorded as *not met* |
| `view_pipeline_plan.md` | Complete 2026-09-09, steps 1–7 |
| `data_contract_plan.md` | Complete 2026-09-11, steps 1–8 — reviewed in [`data_contract_review.md`](../data_contract_review.md) |
| `roi_analysis_plan.md` | Phases 0–2 complete; its commit section and Phase 3 superseded by the two plans below |
| `derived_spectra_plan.md` | Shipped — frozen ROI spectra are synthetic keys on a run (`FrozenSpectrum`) — though its boxes were never ticked |
| `roi_workbench_plan.md` | Shipped — the ROI window (`views/plot/roi/window.py`) and the multi-ROI set (`RoiSetModel`) exist |
| `zarr_l2_cache_plan.md` | Phases 1–1c implemented (`models/cache/zarr_l2_cache.py`); phase 2 onward never started |

The last four were archived on 2026-09-14 at the maintainer's direction, as
complete, stale or superseded. Each note above is drawn from that document's
own header and from the current tree.

Two things worth knowing before reading any of them:

- **Archived does not mean every box is ticked.** `session_and_traces_plan.md`
  closed with three exit criteria recorded as *not met* — file-size targets it
  missed — `view_pipeline_plan.md` carries deferrals, and `derived_spectra_plan.md`
  shipped without anyone ticking a box. Keeping the documents is how that stays
  findable.
- **The reviews stay at the top level**, because they carry the open-item
  lists that current work still draws on.
