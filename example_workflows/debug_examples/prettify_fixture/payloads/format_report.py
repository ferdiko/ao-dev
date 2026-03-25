def format_report(rows: list[dict[str, float]]) -> str:
    total = sum(row["value"] for row in rows)
    highest = max(rows, key=lambda row: row["value"])
    return f"rows={len(rows)} total={total:.2f} top={highest['name']}"
