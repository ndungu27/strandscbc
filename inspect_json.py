"""
Diagnostic: inspect the real structure of a Docling JSON export so we can
fix ingest.py's parsing logic to match what's actually in the file, instead
of guessing.

Usage:
    python inspect_json.py docling_json/AGRICULTURE-Grade-4-30.07.2024.json
"""

import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python inspect_json.py <path_to_json_file>")
    sys.exit(1)

path = Path(sys.argv[1])
with open(path, encoding="utf-8") as f:
    doc = json.load(f)

print(f"Top-level keys: {list(doc.keys())}\n")

texts = doc.get("texts", [])
tables = doc.get("tables", [])
groups = doc.get("groups", [])

print(f"texts: {len(texts)} items")
print(f"tables: {len(tables)} items")
print(f"groups: {len(groups)} items\n")

print("=== First 25 text items (label + text) ===")
for i, item in enumerate(texts[:25]):
    label = item.get("label", "?")
    text = item.get("text", "").strip().replace("\n", " ")
    print(f"[{i}] ({label}): {text[:100]}")

if tables:
    print("\n=== First table structure ===")
    first_table = tables[0]
    print(f"Table keys: {list(first_table.keys())}")
    data = first_table.get("data", {})
    print(f"Data keys: {list(data.keys())}")
    grid = data.get("grid", [])
    print(f"Grid dimensions: {len(grid)} rows")
    for r, row in enumerate(grid[:5]):
        cells = [c.get("text", "").strip().replace("\n", " ")[:40] for c in row]
        print(f"  Row {r}: {cells}")

    print("\n=== Header row (row 0) of every table ===")
    for t_idx, table in enumerate(tables):
        grid = table.get("data", {}).get("grid", [])
        if not grid:
            print(f"Table {t_idx}: EMPTY")
            continue
        header_cells = [c.get("text", "").strip().replace("\n", " ")[:30] for c in grid[0]]
        print(f"Table {t_idx} ({len(grid)} rows x {table.get('data', {}).get('num_cols', '?')} cols): {header_cells}")

    # Print the full first row + second row of the table most likely to be
    # curriculum content: the one with the most columns (KICD grids are wide)
    best_idx = max(
        range(len(tables)),
        key=lambda i: tables[i].get("data", {}).get("num_cols", 0)
    )
    print(f"\n=== Widest table is index {best_idx} -- showing first 3 rows in full ===")
    best_grid = tables[best_idx].get("data", {}).get("grid", [])
    for r, row in enumerate(best_grid[:3]):
        print(f"\n-- Row {r} --")
        for c, cell in enumerate(row):
            text = cell.get("text", "").strip().replace("\n", " ")
            print(f"  Col {c}: {text[:150]}")
            