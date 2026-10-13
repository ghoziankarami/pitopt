# P1–P6 release handoff

Validated again after restoring the cloud environment on 13 October 2026. All six plan gates are GREEN within the software scope of [PLAN_CREDIBILITY_USABILITY.md](PLAN_CREDIBILITY_USABILITY.md). Operational mine-design sign-off remains outside that scope.

| Gate | Evidence and result |
| --- | --- |
| P1 input/result identity | Freshness/restart/download tests pass; example and new Porphyry runtime both current |
| P2 job/save lifecycle | Context, atomic save/publication and cached-design/Generate tests pass |
| P3 data/design contract | Native units/source rows/CRS declarations and explicit shell-versus-bench/domain limitations verified |
| P4 numerical evidence | Public 427 passed/12 conditional skips; private 405 passed/13 conditional skips; gold/nickel/tin corpus and native readback pass again; known-answer/removed-fix/browser evidence retained |
| P5 installation/distribution | Isolated installed wheels (40 UI assets each) pass again; interrupted-install acceptance retained; sealed public demo package matches exact engine/UI wheel and relocated runtime remains current |
| P6 reproducible handoff | Source commits, logs, package checksums, PR body and local deployment procedure recorded |

Source implementation commits: public `796c6c212502ab6536eb5c44d385109d7c9c3dab`; private `b81673b2bdb6e58d1fcbb64bb2d1ea9c74d40a90`. Both are pushed to `fix/credibility-usability-p1-p6`; follow-up documentation commits do not change tested scientific owners. Do not infer remote CI success from local tests; remote CI status could not be read through the restricted GitHub API.

Automatic PR creation was attempted for both repositories and failed with `Post https://api.github.com/graphql: Forbidden`. No PR was created automatically. Open these branch comparison pages and use [the prepared PR description](PR_CREDIBILITY_USABILITY.md):

- Public: https://github.com/ghoziankarami/pitopt/pull/new/fix/credibility-usability-p1-p6
- Private: https://github.com/ghoziankarami/pitopt-private/pull/new/fix/credibility-usability-p1-p6

Deployment is delegated to the owner’s local laptop. No VPS configuration, production service, release tag or main branch was changed. See [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md). Public deployment must use the public synthetic runtime and demo mode; private source and writable user-project features must not be published.

The newly rebuilt Porphyry runtime has 75,696 blocks and 19 periods, duration 544.4 s (~9 minutes; single trial, not a performance distribution). Independent cash/NPV/capacity readback, seven actual Chromium demo screens and public write restrictions pass. Geometric checks report zero cone/order violations under the documented one-block allowance, while the three-bench design still reaches 45.19° against the 42° input. This remains an explicit operational limitation, not a geotechnical acceptance. The big trial was not repeated in private.

The verified archive is retained in `/workspace/scratch/pitopt-release-2026-10-13/artifact/pitopt-synthetic-demo.tar.gz` (about 37 MiB). SHA256:

`a1ff96fcaaac5959dd82d4bfe4fbc1b3cfbc373e4a639109713a16120d987b6e`

All member checksums pass after extraction. Runtime inputs/outputs are git-ignored; a source-only pull will not include them. Rebuild with `make example porphyry` and a fresh wheel, then use `scripts/package_demo_release.py`, or use the verified cloud artifact. The package helper refuses missing/stale results, mismatched wheels, unexpected project IDs, symlinks and overwriting an existing release archive.

Evidence is retained under `/workspace/scratch/pitopt-release-2026-10-13/evidence/`; previous acceptance and negative controls remain under `/workspace/scratch/pitopt-audit/credibility/evidence/`. Dataset source revision remains `7f4cd96f0e521c16e40826aa232cbf760938d1dc` (CC BY 4.0, Orebit.id); nearest-neighbour block models and collar-derived TIN are software fixtures, not certified geological estimates. Native Windows/macOS and target mining/CAD interoperability remain unverified.
