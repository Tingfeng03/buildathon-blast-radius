"""Collect pinned executor pool-task coverage using the same tracer as the optimizer."""

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "phase02"))
import trace_workers as tracer


started = set()


def traced_task(node, function, args, kwargs):
    if node not in started:
        started.add(node)
        (tracer.OUTPUT / f"tasks-{os.getpid()}.json").write_text(json.dumps(sorted(started)))
    return tracer.traced_call(node, function, args, kwargs)


def main():
    submitted = set()
    submit = ProcessPoolExecutor.submit

    def trace_submit(pool, function, /, *args, **kwargs):
        node = tracer._current_test
        if node is None:
            raise ValueError("Cannot attribute a process-pool submission to a test")
        submitted.add(node)
        return submit(pool, traced_task, node, function, args, kwargs)

    ProcessPoolExecutor.submit = trace_submit
    try:
        status = pytest.main(["-q", "-p", "no:cacheprovider", "tests/test_executor.py"],
                             plugins=[tracer.OptimizerTrace()])
    finally:
        ProcessPoolExecutor.submit = submit
    (tracer.OUTPUT / "executor-run.json").write_text(json.dumps({
        "status": int(status), "submitted_ids": sorted(submitted),
    }))
    return status


if __name__ == "__main__":
    sys.exit(main())
