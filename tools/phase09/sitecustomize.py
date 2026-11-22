"""Flag fixture reads in Python subprocesses that have no test or scope owner."""

import os
import sys


def fixture_path(name):
    if not isinstance(name, (str, bytes)):
        return None
    path = os.path.realpath(os.fsdecode(name))
    if path.startswith("/src/tests/fixtures/"):
        return path.removeprefix("/src/")
    return None


def audit(event, args):
    if event == "open" and (path := fixture_path(args[0])):
        with open(os.environ["BLAST_RADIUS_CHILD_OPENS"], "a", encoding="utf-8") as stream:
            stream.write(path + "\n")


if "BLAST_RADIUS_CHILD_OPENS" in os.environ:
    sys.addaudithook(audit)
