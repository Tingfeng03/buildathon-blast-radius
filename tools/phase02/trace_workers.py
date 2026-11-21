"""Trace optimizer tasks separately from the parent pytest coverage."""

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing.util import Finalize
from pathlib import Path

import coverage
import pytest

ROOT = Path("/src")
OUTPUT = Path("/evidence")
_trace = None
_current_test = None
_submitted = set()


def export_worker():
    _trace.stop()
    data = _trace.get_data()
    sources = {
        str(Path(filename).relative_to(ROOT)): {
            line: sorted(ids) for line, ids in data.contexts_by_lineno(filename).items()
        }
        for filename in sorted(data.measured_files())
    }
    record = {"pid": os.getpid(), "sources": sources}
    (OUTPUT / f"worker-{os.getpid()}.json").write_text(json.dumps(record), encoding="utf-8")


def traced_call(nodeid, function, args, kwargs):
    global _trace
    if _trace is None:
        _trace = coverage.Coverage(
            config_file=False, data_file=f"/tmp/phase02-coverage-{os.getpid()}.sqlite",
            include=["/src/sqlglot/*"],
        )
        _trace.start()
        Finalize(None, export_worker, exitpriority=10)
    _trace.switch_context(nodeid)
    try:
        return function(*args, **kwargs)
    finally:
        _trace.switch_context("")


class OptimizerTrace:
    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item):
        global _current_test
        _current_test = item.nodeid
        try:
            return (yield)
        finally:
            _current_test = None


def main():
    from tests.test_optimizer import parse_and_optimize

    submit = ProcessPoolExecutor.submit

    def traced_submit(pool, fn, /, *args, **kwargs):
        if fn is parse_and_optimize:
            sink = _current_test or ""
            _submitted.add(sink)
            return submit(pool, traced_call, sink, fn, args, kwargs)
        return submit(pool, fn, *args, **kwargs)

    ProcessPoolExecutor.submit = traced_submit
    start = time.monotonic()
    targets = sys.argv[1:] or ["tests/test_optimizer.py"]
    try:
        status = pytest.main(["-q", "-p", "no:cacheprovider", *targets], plugins=[OptimizerTrace()])
    finally:
        ProcessPoolExecutor.submit = submit
    (OUTPUT / "worker-run.json").write_text(json.dumps({
        "status": int(status), "parent_pid": os.getpid(), "wall_seconds": time.monotonic() - start,
        "submitted_ids": sorted(_submitted),
    }), encoding="utf-8")
    return status


if __name__ == "__main__":
    sys.exit(main())
