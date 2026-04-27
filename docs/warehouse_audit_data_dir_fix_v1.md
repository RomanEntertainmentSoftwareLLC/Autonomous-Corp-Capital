# Warehouse audit data-directory fix v1

`tools/init_warehouse.py` and `tools/db_status.py` use:

```text
data/warehouse.sqlite
```

The old `tools/warehouse_audit.py` only searched under `state/`, so a freshly initialized canonical warehouse was falsely reported as missing.

This patch updates `tools/warehouse_audit.py` to search both:

```text
data/
state/
```

It also reports the searched directories, data/state directory presence, tables, and views. An empty initialized warehouse should now return `warehouse_empty_or_unverified` rather than `artifact_only_no_sqlite_warehouse_found`.
