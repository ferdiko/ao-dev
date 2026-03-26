# Release Handoff

Use `python -m app`, `SELECT * FROM metrics`, and `curl /health` in the rendered view.

- This field should look like markdown.
- It mixes prose with inline `python`, `sql`, `bash`, and `tsx`.
- The fenced blocks below should stay recognizable as code.

```bash
uv run python inject_prettify_run.py
```

```json
{"status":"ok","count":3,"files":["example.docx","example.xlsx","example.pptx"]}
```
