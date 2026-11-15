# R1 Public Handoff Summary

Review date: 2026-11-15  
Status: engineering handoff verified; image quality remains on hold; final R1 acceptance is not complete.

## Scope and source

This R1 review covers 320 paired scenes sampled from the pinned xBD snapshot `b98724026e844e1fccd879c95e9f09f03c56e6f8`. The source is distributed under CC BY-NC-SA 3.0. The public data manifest records the source revision, license, aggregate inventory, and a digest of the full local source manifest. It intentionally omits scene IDs and per-file records so held-out test assets are not enumerated publicly.

No source imagery, prepared imagery, labels, geospatial result files, model weights, or runtime output files are included in this repository handoff. They remain in the local D-drive project workspace.

## R1 review results

- 320 paired scenes were screened; 280 pairs were prepared for downstream contract review.
- All 320 pairs remain quarantined for image-quality use. Zero pairs are released for model use.
- Registration evidence was insufficient for 317 pairs; 3 pairs exceeded the engineering misalignment screen.
- Label-derived transforms could be reconstructed for 562 of 640 image time slices; 78 remain unresolved. A transform fitted from labels does not establish absolute positional accuracy.
- The independent receiver check verified file and input-contract properties for the 280 prepared pairs. This is not a human quality sign-off.
- No ground checkpoints or original official geotransforms were available for this review. Absolute positional accuracy is unknown; human scope acceptance and downstream receipt remain pending.

The engineering screening thresholds are documented in the local review evidence and have not been approved as project-wide spatial acceptance criteria. No scene was promoted to usable based solely on file readability or successful preparation.

## Acceptance

`final_r1_acceptance` is `false`. This summary records completed engineering checks and the outstanding quality hold; it does not claim R1 acceptance or authorize operational use.

## Reproducibility and retained evidence

The local review package is retained at `outputs/xbd_expanded/r1_handoff_v2/`. It includes the scene-level review evidence, quarantine list, receiver verification, and human-review template. These runtime outputs and geospatial entities are intentionally excluded from Git under the repository data policy.

The aggregate provenance and screening inventory is in [r1_handoff_screening_v2.json](../../data/manifests/r1_handoff_screening_v2.json). The earlier expanded-model research metrics and limitations are documented separately in [STAGE2_EXPANDED_REPORT.md](STAGE2_EXPANDED_REPORT.md); R1 input readiness must not be conflated with model effectiveness or full Stage 2 acceptance.
