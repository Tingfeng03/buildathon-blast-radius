# Blast Radius development guidelines

> Draft for review, pending discussion of the selector architecture.

This project selects and schedules sqlglot tests for independent patches. Read [HACKATHON_RULES.md](HACKATHON_RULES.md) for competition constraints, [SCORING.md](SCORING.md) for the exact input, output, and cost rules, and [INVESTIGATION.md](INVESTIGATION.md) for measured baselines and known gaps.

## Development workflow

Use [GOALS.md](GOALS.md) for project outcomes and [PLANS.md](PLANS.md) for architectural decisions, phase boundaries, and acceptance criteria.

Follow the phase-based workflow from the [OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex), scaled to this project.

1. **Plan.** Use `PLANS.md` for the roadmap and `harness/build/` for individual phases. Define each phase's scope, dependencies, acceptance criteria, and verification commands. Discuss material design choices with the user before treating them as decided.
2. **Confirm scope.** Start with a read-only check of the relevant rules, plan, code, and prior results. Summarize what the phase will change and how it will be verified. Start implementation once the user has authorized that phase.
3. **Implement and verify.** Work on one phase at a time. For behavior changes, reproduce the gap with a focused check when practical, make the smallest change that meets the acceptance criteria, and verify the result. Review the diff for regressions and unintended scope changes.
4. **Record and hand off.** In `harness/build-log.md`, record what changed, the checks actually run, their results, and any blockers. Use `harness/context/` for decisions and findings future phases need. Report the outcome and return control to the user before starting the next phase. Treat commits, pushes, and submission as separate actions unless the user includes them in the authorized scope.

Create planning and harness files as the work calls for them. Use the build log to improve the workflow when it reveals recurring problems. Use the starter kit as a reference and exclude `.investigation/` from the submission.

## Competition feedback

- Use sample answers for local scoring and diagnosis. Derive any precomputed dependency maps from the pinned sqlglot source and tests. Document how to regenerate them.
- For changes that affect selection or scheduling, compare with the previous result and the four-worker, all-tests sample baseline (1104.510 simulated seconds, zero misses). Report missed commits and simulated cost separately from selector CPU, when measured.

## Code quality

- Keep patch interpretation, test selection, and worker scheduling easy to reason about independently. Prefer simple, deterministic logic and dependencies with a clear purpose.
- Use the supplied catalogue for test numbers and recorded durations. Use whole milliseconds for scoring calculations. Reserve stdout for the required JSON lines and send diagnostics to stderr.
- Give uncertain patch cases an explicit, tested behavior. Avoid assumptions based on sample patch IDs, sample ordering, or the observed mix of changes.

## Testing

- Add focused regression tests for behavioral changes where the sample does not cover the case. Useful cases include multi-file and insertion-only diffs, unknown dependency evidence, empty selections, and worker overhead.
- Run the starter kit's `score.py` against the full sample when selection or scheduling changes. For container changes and submission checks, build and run on Linux AMD64 with the starter's runtime flags. Use `make` or equivalent Docker commands.
- When reproducing sqlglot test behavior, use the pinned source, starter base image and locked dependencies, and `SKIP_INTEGRATION=0`. Count a failing subtest as a failure of its parent test.

## Developer Understanding

After completing each build phase:

- Summarize the changes and their architectural significance.
- Identify the primary files and functions introduced or modified.
- Explain the main execution and data flows.
- Highlight important design decisions and trade-offs.
- Identify assumptions or limitations relevant to future phases.
- Provide a suggested walkthrough order for understanding the implementation.

Keep explanations concise and reference actual repository files and functions. Do not generate extensive documentation unless requested.
