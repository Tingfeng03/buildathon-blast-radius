"""Define independent edits for measuring the expensive Phase 6 selections."""

from label_structural import main


CASES = {
    "development-default": (
        "sqlglot/optimizer/normalize.py",
        "max_distance: int = 128",
        "max_distance: int = 1",
    ),
    "development-definition": (
        "sqlglot/optimizer/normalize.py",
        "def normalized(",
        "def _normalize_noop():\n    return None\n\n\ndef normalized(",
    ),
    "development-setting": (
        "sqlglot/generators/databricks.py",
        "    exp.DType.TIMESTAMPTZ,\n",
        "",
    ),
    "development-nested": (
        "sqlglot/optimizer/eliminate_ctes.py",
        "                    cte_node.pop()\n",
        "                    if count == 0:\n                        cte_node.pop()\n",
    ),
    "holdout-default": (
        "sqlglot/parsers/bigquery.py",
        "def _parse_unnest(self, with_alias: bool = True)",
        "def _parse_unnest(self, with_alias: bool = False)",
    ),
    "holdout-setting": (
        "sqlglot/dialects/postgres.py",
        "    TIME_MAPPING = {\n",
        "    TIME_MAPPING = {\n        'yyyymm': '%Y%m',\n",
    ),
    "holdout-definition": (
        "sqlglot/dialects/duckdb.py",
        "    INDEX_OFFSET = 1\n",
        "    INDEX_OFFSET = 1\n    EXAMPLE_SETTING = True\n",
    ),
}


if __name__ == "__main__":
    main(CASES)
