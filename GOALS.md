# Blast Radius project goals

Build a Dockerized selector that gives each independent sqlglot patch a low-cost test schedule while including every test likely to fail. The project succeeds competitively when it reduces total simulated CI seconds on unseen patches, including miss penalties and selector CPU time. The ideal schedule for a harmless patch is empty.

## Expected outcomes and evidence

| Outcome | How we will judge it |
| --- | --- |
| Valid submission | A clean build produces a Linux AMD64 image that emits exactly one accepted JSON line per patch and completes the batch under the competition limits. |
| Cheaper CI with reliable failure detection | Compare each candidate with the previous version and the full-suite reference. Report missed commits, scheduled test cost, penalties, and measured selector CPU separately. Aim for zero observed misses on the sample and independently labeled validation patches. Unseen performance is determined by the final scorer. |
| Reproducible results | A teammate can regenerate any shipped dependency map from the pinned base commit, run the image against sample inputs, and reproduce the simulated score with the organizer's scorer. |

On the supplied 30 patches, running all tests with four workers costs **1104.510 simulated seconds with zero misses**. Selecting readers of known optimizer fixtures and using the full suite elsewhere gives a phase 01 target of **827.874 seconds with zero misses**. The local scorer validated both sets of investigation outputs. These figures exclude selector CPU. The competition brief separately lists **1614.1 seconds** as its starter baseline.

## Technical constraints

- Every patch targets sqlglot commit `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. Read patches and the numbered test catalogue from `/data`. Use each selected test at most once per patch, across up to eight workers. Send logs to stderr and keep stdout within 2 MB.
- For each patch, the scorer adds the busiest worker's recorded seconds, two seconds per nonempty worker, and 300 seconds if any failing test was omitted. It also charges the selector's CPU time across the batch.
- A clean build gets four cores, 8 GB RAM, ten minutes, and the download sources allowed by the rules. The public submission repository must fit within 20 MB and have a root Dockerfile.
- Runtime is offline with two cores, 4 GB RAM, three minutes per batch (4.5 in the final), a read-only root, 64 MB of temporary storage, and a 256-process limit. Files needed by the selector must be readable by user `nobody`.
- Use sample answers only for evaluation and diagnosis. Permitted maps describe dependencies observed or derived from the pinned source and tests. Patch-to-failure and edit-kind-to-failure lookup tables are prohibited.

See the [competition rules](HACKATHON_RULES.md), [exact scoring contract](SCORING.md), and [investigation results](INVESTIGATION.md).
