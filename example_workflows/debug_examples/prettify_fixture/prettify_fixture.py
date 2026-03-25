from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


PROJECT_ID = "7cb0ae81-44c0-48a9-93d4-c6100c444f01"
PROJECT_NAME = "Sovara UI Prettify Fixture"
PROJECT_DESCRIPTION = "Synthetic run with recursive JSON, string classification, and attachments for prettified-view QA."

PROJECT_ROOT = Path(__file__).resolve().parent
PAYLOADS_DIR = PROJECT_ROOT / "payloads"
USER_FILES = PROJECT_ROOT.parent / "user_files"

FILE_MIME_TYPES = {
    "example.pdf": "application/pdf",
    "example.png": "image/png",
    "sample_program.jpg": "image/jpeg",
    "example.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "example.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "example.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _read_payload(name: str) -> str:
    return (PAYLOADS_DIR / name).read_text(encoding="utf-8").strip()


def _b64(filename: str) -> str:
    return base64.b64encode((USER_FILES / filename).read_bytes()).decode("utf-8")


def _data_url(filename: str) -> str:
    mime_type = FILE_MIME_TYPES[filename]
    return f"data:{mime_type};base64,{_b64(filename)}"


def _document_blob(filename: str) -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": FILE_MIME_TYPES[filename],
        "data": _b64(filename),
    }


def _deep_chain(terminal_json_string: str) -> dict[str, Any]:
    return {
        "level": 1,
        "kind": "root",
        "next": {
            "level": 2,
            "kind": "branch",
            "next": {
                "level": 3,
                "kind": "branch",
                "next": {
                    "level": 4,
                    "kind": "leaf",
                    "terminal_json_string": terminal_json_string,
                },
            },
        },
    }


def _rows() -> list[dict[str, Any]]:
    return [
        {"name": "alpha", "score": 1, "ok": True},
        {"name": "beta", "score": 2.5, "ok": False},
        {"name": "gamma", "score": 3, "ok": True},
    ]


def build_prettify_fixture() -> dict[str, Any]:
    markdown = _read_payload("rich_markdown.md")
    python_snippet = _read_payload("format_report.py")
    tsx_snippet = _read_payload("widget.tsx")
    sql_snippet = _read_payload("report.sql")
    xml_snippet = _read_payload("layout.xml")
    json_object_string = _read_payload("nested_object.json")
    json_array_string = _read_payload("nested_list.json")
    almost_json = _read_payload("almost_json.txt")

    embedded_object = json.loads(json_object_string)
    embedded_list = json.loads(json_array_string)
    long_markdown = markdown + "\n\n" + "\n".join(
        f"- preview line {index}: `token_{index}`" for index in range(1, 9)
    )

    return {
        "name": "UI Prettify Fixture",
        "description": PROJECT_DESCRIPTION,
        "nodes": [
            {
                "id": "fixture_recursive_json",
                "label": "Recursive JSON",
                "model": "synthetic/recursive-json",
                "border_color": "#1a7f37",
                "incoming_edges": [],
                "input": {
                    "goal": "Exercise object and list recursion with scalar leaves.",
                    "focus": ["headers", "nested boxes", "arrays", "scalar types"],
                    "constraint": "Node payloads stay object-shaped because graph parsing currently expects records.",
                },
                "output": {
                    "header": "Recursive object and list cases",
                    "object_card": {
                        "headline": "Nested branch",
                        "details": embedded_object,
                    },
                    "array_branch": [
                        {"kind": "row", "payload": {"markdown": markdown}},
                        {"kind": "row", "payload": embedded_object},
                        7,
                        3.14159,
                        True,
                        None,
                    ],
                    "type_gallery": {
                        "int_value": 7,
                        "float_value": 3.14159,
                        "bool_true": True,
                        "bool_false": False,
                        "null_value": None,
                    },
                    "table_like_rows": _rows(),
                    "json_array_leaf": embedded_list,
                },
            },
            {
                "id": "fixture_string_cases",
                "label": "String Classification",
                "model": "synthetic/string-classifier",
                "border_color": "#0969da",
                "incoming_edges": ["fixture_recursive_json"],
                "input": {
                    "goal": "Exercise string heuristics and recursive parsing.",
                    "focus": ["json strings", "markdown", "code fences", "xml", "fallback"],
                    "suggested_precedence": ["json", "fenced code", "xml", "markdown", "plain text"],
                },
                "output": {
                    "json_object_string": json_object_string,
                    "json_array_string": json_array_string,
                    "markdown_string": markdown,
                    "fenced_python": f"```python\n{python_snippet}\n```",
                    "fenced_tsx": f"```tsx\n{tsx_snippet}\n```",
                    "fenced_sql": f"```sql\n{sql_snippet}\n```",
                    "xml_string": xml_snippet,
                    "unfenced_python": python_snippet,
                    "mixed_inline_code_markdown": "Use `python`, `sql`, `bash`, and `tsx` inline when rendering this field.",
                    "ambiguous_fallback": almost_json,
                },
            },
            {
                "id": "fixture_attachments",
                "label": "Attachments",
                "model": "synthetic/attachments",
                "border_color": "#bf8700",
                "incoming_edges": ["fixture_string_cases"],
                "input": {
                    "goal": "Exercise file detection for PDFs, images, and Office documents.",
                    "focus": ["mime_type siblings", "data URLs", "nested attachment arrays"],
                    "files": sorted(FILE_MIME_TYPES),
                },
                "output": {
                    "pdf_document": _document_blob("example.pdf"),
                    "png_document": _document_blob("example.png"),
                    "jpg_image_data_url": _data_url("sample_program.jpg"),
                    "office_documents": [
                        _document_blob("example.docx"),
                        _document_blob("example.xlsx"),
                        _document_blob("example.pptx"),
                    ],
                    "mixed_gallery": {
                        "documents": {
                            "pdf": _document_blob("example.pdf"),
                            "docx": _document_blob("example.docx"),
                        },
                        "images": [
                            _document_blob("example.png"),
                            _document_blob("sample_program.jpg"),
                        ],
                        "notes_markdown": markdown,
                    },
                },
            },
            {
                "id": "fixture_stress",
                "label": "Stress Cases",
                "model": "synthetic/stress",
                "border_color": "#8250df",
                "incoming_edges": ["fixture_attachments"],
                "input": {
                    "goal": "Exercise previews, uniform rows, depth limits, and mixed leaves.",
                    "focus": ["long text", "deep recursion", "uniform arrays", "nested json strings"],
                },
                "output": {
                    "preview_threshold_candidate": long_markdown,
                    "uniform_rows": [
                        {"column": "alpha", "score": 1, "ok": True},
                        {"column": "beta", "score": 2, "ok": False},
                        {"column": "gamma", "score": 3, "ok": True},
                        {"column": "delta", "score": 4, "ok": True},
                    ],
                    "primitive_list": [
                        "plain text",
                        7,
                        2.5,
                        True,
                        False,
                        None,
                        "<item status=\"xml\" />",
                    ],
                    "deep_chain": _deep_chain(json_object_string),
                    "nested_string_mix": {
                        "markdown_in_json_string": json.dumps(
                            {"body": markdown, "xml": xml_snippet},
                            indent=2,
                        ),
                        "list_in_json_string": json.dumps(embedded_list, indent=2),
                        "code_and_logs": (
                            f"{python_snippet}\n\n"
                            "# log tail\n"
                            "INFO rendered=4\n"
                            "WARN fallback=1"
                        ),
                    },
                },
            },
        ],
    }
