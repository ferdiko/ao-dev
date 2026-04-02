"""Derived step-local content view for trace-chat editing."""

from dataclasses import dataclass
import re
from typing import Any, Literal, TypeAlias

from .content_utils import extract_text_content, is_text_block_list, split_prompt, stringify_field

JsonPath: TypeAlias = tuple[str | int, ...]
InputOrOutput = Literal["input", "output"]
_CONTENT_ID_RE = re.compile(r"^c(\d+)$")


@dataclass
class ContentUnit:
    content_id: str
    input_or_output: InputOrOutput
    dict_path: JsonPath
    text: str


@dataclass
class StepContentView:
    input_to_show: dict
    output_to_show: dict
    units: list[ContentUnit]


def format_dict_path(dict_path: JsonPath) -> str:
    if not dict_path:
        return "<root>"
    return ".".join(str(part) for part in dict_path)


def _append_content_units(
    units: list[ContentUnit],
    value: Any,
    *,
    input_or_output: InputOrOutput,
    dict_path: JsonPath,
) -> None:
    if is_text_block_list(value):
        paragraphs = split_prompt(extract_text_content(value))
        for paragraph in paragraphs:
            units.append(ContentUnit(
                content_id=f"c{len(units)}",
                input_or_output=input_or_output,
                dict_path=dict_path,
                text=paragraph,
            ))
        return

    if isinstance(value, dict):
        if not value:
            if not dict_path:
                return
            rendered = stringify_field(value).strip()
            paragraphs = split_prompt(rendered) if rendered else [""]
            for paragraph in paragraphs:
                units.append(ContentUnit(
                    content_id=f"c{len(units)}",
                    input_or_output=input_or_output,
                    dict_path=dict_path,
                    text=paragraph,
                ))
            return
        for key, child in value.items():
            _append_content_units(
                units,
                child,
                input_or_output=input_or_output,
                dict_path=dict_path + (key,),
            )
        return

    if isinstance(value, list):
        if not value:
            if not dict_path:
                return
            rendered = stringify_field(value).strip()
            paragraphs = split_prompt(rendered) if rendered else [""]
            for paragraph in paragraphs:
                units.append(ContentUnit(
                    content_id=f"c{len(units)}",
                    input_or_output=input_or_output,
                    dict_path=dict_path,
                    text=paragraph,
                ))
            return
        for index, child in enumerate(value):
            _append_content_units(
                units,
                child,
                input_or_output=input_or_output,
                dict_path=dict_path + (index,),
            )
        return

    if isinstance(value, str):
        paragraphs = split_prompt(value)
    else:
        rendered = stringify_field(value).strip()
        paragraphs = split_prompt(rendered) if rendered else [""]
    for paragraph in paragraphs:
        units.append(ContentUnit(
            content_id=f"c{len(units)}",
            input_or_output=input_or_output,
            dict_path=dict_path,
            text=paragraph,
        ))


def build_step_content_view(input_to_show: dict, output_to_show: dict) -> StepContentView:
    units: list[ContentUnit] = []
    _append_content_units(units, input_to_show or {}, input_or_output="input", dict_path=())
    _append_content_units(units, output_to_show or {}, input_or_output="output", dict_path=())
    return StepContentView(
        input_to_show=input_to_show or {},
        output_to_show=output_to_show or {},
        units=units,
    )


def resolve_content_unit(view: StepContentView, content_id) -> ContentUnit:
    normalized = str(content_id).strip() if content_id is not None else ""
    match = _CONTENT_ID_RE.fullmatch(normalized)
    if not match:
        raise ValueError("Invalid content_id: must look like c0, c1, c2, ...")
    index = int(match.group(1))
    if index < 0 or index >= len(view.units):
        raise KeyError(normalized)
    return view.units[index]


def get_path_value(value: Any, dict_path: JsonPath) -> Any:
    current = value
    for part in dict_path:
        current = current[part]
    return current


def set_path_value(value: Any, dict_path: JsonPath, new_value: Any) -> Any:
    if not dict_path:
        return new_value

    current = value
    for part in dict_path[:-1]:
        current = current[part]
    current[dict_path[-1]] = new_value
    return value


def set_text_value(root: Any, dict_path: JsonPath, new_text: str) -> Any:
    current = get_path_value(root, dict_path) if dict_path else root

    if is_text_block_list(current) and isinstance(current, list):
        updated = []
        inserted = False
        for block in current:
            if isinstance(block, dict) and block.get("type") == "text":
                if not inserted:
                    updated.append({**block, "text": new_text})
                    inserted = True
                continue
            updated.append(block)
        if not inserted:
            updated.append({"type": "text", "text": new_text})
        return set_path_value(root, dict_path, updated)

    return set_path_value(root, dict_path, new_text)


def _matching_unit_indices(view: StepContentView, unit: ContentUnit) -> list[int]:
    return [
        index for index, candidate in enumerate(view.units)
        if candidate.input_or_output == unit.input_or_output and candidate.dict_path == unit.dict_path
    ]


def replace_content_unit_text(view: StepContentView, content_id, new_text: str) -> ContentUnit:
    unit = resolve_content_unit(view, content_id)
    unit.text = new_text
    sync_content_units_to_root(view, unit.input_or_output, unit.dict_path)
    return unit


def delete_content_unit_from_view(view: StepContentView, content_id) -> ContentUnit:
    unit = resolve_content_unit(view, content_id)
    unit_index = next(index for index, candidate in enumerate(view.units) if candidate is unit)
    deleted = view.units.pop(unit_index)
    sync_content_units_to_root(view, deleted.input_or_output, deleted.dict_path)
    for index, candidate in enumerate(view.units):
        candidate.content_id = f"c{index}"
    return deleted


def sync_content_units_to_root(view: StepContentView, input_or_output: InputOrOutput, dict_path: JsonPath) -> None:
    texts = [
        candidate.text for candidate in view.units
        if candidate.input_or_output == input_or_output and candidate.dict_path == dict_path
    ]
    new_text = "\n\n".join(texts) if texts else ""
    root = view.input_to_show if input_or_output == "input" else view.output_to_show
    set_text_value(root, dict_path, new_text)
