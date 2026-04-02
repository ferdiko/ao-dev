"""API routes for the priors backend child service."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from sovara.server.priors_backend.deps import get_prior_store, get_scope_from_request
from sovara.server.priors_backend.events import publish
from sovara.server.llm_backend import resolve_model
from sovara.server.priors_backend.llm.lesson_retriever import (
    build_folder_tree_summary,
    retrieve_relevant_priors,
)
from sovara.server.priors_backend.llm.lesson_summarizer import (
    fallback_prior_summary,
    generate_prior_summary,
)
from sovara.server.priors_backend.llm.lesson_validator import validate_prior
from sovara.server.priors_backend.logger import logger
from sovara.server.priors_backend.retrieval_cache import (
    get_cached_retrieval,
    store_cached_retrieval,
)
from sovara.server.priors_backend.prefix_cache import (
    clear_scope_prefix_cache,
    lookup_longest_prefix,
    store_prefix,
)

router = APIRouter(prefix="/api/v1")


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    if ".." in path:
        raise HTTPException(status_code=400, detail="Path must not contain '..'")
    if path.startswith("/"):
        raise HTTPException(status_code=400, detail="Path must not start with '/'")
    if "//" in path:
        raise HTTPException(status_code=400, detail="Path must not contain '//'")
    for segment in path.rstrip("/").split("/"):
        if segment.startswith("."):
            raise HTTPException(status_code=400, detail=f"Path segment '{segment}' must not start with '.'")
    return path if path.endswith("/") else path + "/"


def _build_injected_context(priors: list[dict]) -> str:
    if not priors:
        return ""
    manifest = {
        "priors": [
            {"id": prior["id"]}
            for prior in priors
        ]
    }
    blocks = [f"## {prior['name']}\n{prior['content']}" for prior in priors]
    return (
        "<sovara-priors>\n"
        f"<!-- {json.dumps(manifest, separators=(',', ':'))} -->\n"
        + "\n\n".join(blocks)
        + "\n</sovara-priors>"
    )


def _validation_to_feedback(validation) -> dict:
    path_assessment = None
    if validation.path_assessment:
        path_assessment = {
            "path_is_correct": validation.path_assessment.path_is_correct,
            "suggested_path": validation.path_assessment.suggested_path,
            "path_reasoning": validation.path_assessment.path_reasoning,
        }
    conflict_details = [
        {
            "prior_id": detail.prior_id,
            "conflict_type": detail.conflict_type,
            "explanation": detail.explanation,
            "resolution_suggestion": detail.resolution_suggestion,
            "creation_trace_id": detail.creation_trace_id,
        }
        for detail in validation.conflict_details
    ]
    return {
        "feedback": validation.feedback,
        "severity": validation.severity,
        "conflicting_prior_ids": validation.conflicting_prior_ids,
        "path_assessment": path_assessment,
        "conflict_details": conflict_details,
    }


class PriorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = Field(None, min_length=1, max_length=1000)
    content: str = Field(..., min_length=1)
    path: str = ""
    creation_trace_id: Optional[str] = None
    trace_source: Optional[str] = None


class PriorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    summary: Optional[str] = Field(None, min_length=1, max_length=1000)
    content: Optional[str] = Field(None, min_length=1)
    path: Optional[str] = None


class PriorDraftCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    path: str = ""


class PriorSubmitRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1)
    path: Optional[str] = None


class PriorQueryRequest(BaseModel):
    path: Optional[str] = None


class FolderLsRequest(BaseModel):
    path: str = ""


class FolderCreateRequest(BaseModel):
    path: str


class FolderMoveRequest(BaseModel):
    path: str
    new_path: str


class FolderDeleteRequest(BaseModel):
    path: str


class PriorItemRef(BaseModel):
    kind: Literal["prior", "folder"]
    id: Optional[str] = None
    path: Optional[str] = None


class PriorItemsCopyRequest(BaseModel):
    items: list[PriorItemRef] = Field(default_factory=list)
    destination_path: str = ""
    as_draft: bool = False


class PriorItemsMoveRequest(BaseModel):
    items: list[PriorItemRef] = Field(default_factory=list)
    destination_path: str = ""


class PriorItemsDeleteRequest(BaseModel):
    items: list[PriorItemRef] = Field(default_factory=list)


class PriorRetrieveRequest(BaseModel):
    context: str = Field(..., min_length=1)
    base_path: str = ""
    model: Optional[str] = None
    ignore_prior_ids: list[str] = Field(default_factory=list)


class PrefixCacheLookupRequest(BaseModel):
    base_path: str = ""
    clean_pairs: list[dict[str, str]] = Field(default_factory=list)


class PrefixCacheStoreRequest(BaseModel):
    base_path: str = ""
    clean_pairs: list[dict[str, str]] = Field(default_factory=list)
    injected_pairs: list[dict[str, str]] = Field(default_factory=list)
    prior_ids: list[str] = Field(default_factory=list)


class RetrievedPrior(BaseModel):
    id: str
    name: str
    summary: str
    content: str
    path: str


class PriorRetrieveResponse(BaseModel):
    context: str
    base_path: str
    priors: List[RetrievedPrior]
    prior_count: int
    priors_revision: int
    rendered_priors_block: str
    model_used: str


def _normalize_item_refs(items: list[PriorItemRef]) -> list[PriorItemRef]:
    normalized: list[PriorItemRef] = []
    seen: set[tuple[str, str]] = set()

    folder_paths = {
        _normalize_path(item.path or "")
        for item in items
        if item.kind == "folder" and item.path
    }

    for item in items:
        if item.kind == "prior":
            if not item.id:
                raise HTTPException(status_code=400, detail="Prior item is missing id")
            key = ("prior", item.id)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(PriorItemRef(kind="prior", id=item.id))
            continue

        path = _normalize_path(item.path or "")
        if not path:
            raise HTTPException(status_code=400, detail="Folder item is missing path")
        if any(path != parent and path.startswith(parent) for parent in folder_paths):
            continue
        key = ("folder", path)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(PriorItemRef(kind="folder", path=path))

    normalized.sort(key=lambda item: (item.kind != "folder", len((item.path or "").split("/"))))
    return normalized


def _copied_item_payload(item: dict, kind: Literal["prior", "folder"]) -> dict:
    if kind == "folder":
        path = item["path"]
        return {
            "kind": "folder",
            "path": path,
            "name": path.rstrip("/").split("/")[-1] if path else "",
        }
    return {
        "kind": "prior",
        "id": item["id"],
        "path": item["path"],
        "name": item["name"],
    }


def _active_only(priors: list[dict]) -> list[dict]:
    return [prior for prior in priors if prior.get("prior_status", "active") == "active"]


def _folder_contains_active_priors(store, path: str) -> bool:
    return any(prior.get("prior_status", "active") == "active" for prior in store.list_all(path=path, include_content=False))


def _items_affect_active_world(store, items: list[PriorItemRef]) -> bool:
    for item in items:
        if item.kind == "prior":
            prior = store.get(item.id or "")
            if prior and prior.get("prior_status", "active") == "active":
                return True
            continue
        path = _normalize_path(item.path or "")
        if path and _folder_contains_active_priors(store, path):
            return True
    return False


def _clear_scope_prefix_cache_for_request(request: Request) -> None:
    user_id, project_id = get_scope_from_request(request)
    clear_scope_prefix_cache(user_id=user_id, project_id=project_id)


@router.get("/priors/scope")
def get_scope(request: Request):
    store = get_prior_store(request)
    return store.read_scope_metadata()


@router.post("/priors/prefix-cache/lookup")
def lookup_prefix_cache_endpoint(request: Request, body: PrefixCacheLookupRequest):
    user_id, project_id = get_scope_from_request(request)
    base_path = _normalize_path(body.base_path)
    match = lookup_longest_prefix(
        user_id=user_id,
        project_id=project_id,
        base_path=base_path,
        clean_pairs=body.clean_pairs,
    )
    if match is None:
        return {"found": False}
    return {"found": True, **match}


@router.post("/priors/prefix-cache/store")
def store_prefix_cache_endpoint(request: Request, body: PrefixCacheStoreRequest):
    user_id, project_id = get_scope_from_request(request)
    base_path = _normalize_path(body.base_path)
    store_prefix(
        user_id=user_id,
        project_id=project_id,
        base_path=base_path,
        clean_pairs=body.clean_pairs,
        injected_pairs=body.injected_pairs,
        prior_ids=body.prior_ids,
    )
    return {"stored": True}


@router.get("/priors")
def list_priors(request: Request, path: Optional[str] = Query(default=None)):
    store = get_prior_store(request)
    priors = store.list_all(path=_normalize_path(path) if path else None, include_content=True)
    return {"priors": priors}


@router.get("/priors/{prior_id}")
def get_prior(request: Request, prior_id: str):
    store = get_prior_store(request)
    prior = store.get(prior_id)
    if prior is None:
        raise HTTPException(status_code=404, detail="Prior not found")
    return prior


@router.post("/query/priors")
def query_priors(request: Request, body: PriorQueryRequest):
    store = get_prior_store(request)
    path = _normalize_path(body.path) if body.path else ""
    if body.path is not None and not store.folder_exists(path):
        raise HTTPException(status_code=404, detail="Folder not found")
    priors = _active_only(store.list_all(path=path if body.path is not None else None, include_content=True))
    return {
        "path": path,
        "priors": priors,
        "injected_context": _build_injected_context(priors),
    }


@router.post("/priors/folders/ls")
def folder_ls(request: Request, body: FolderLsRequest):
    store = get_prior_store(request)
    path = _normalize_path(body.path)
    result = store.list_folders(path, include_content=False)
    return {
        "path": path,
        "folders": result["folders"],
        "priors": result["priors"],
        "prior_count": result["prior_count"],
    }


@router.post("/priors/folders")
def create_folder(request: Request, body: FolderCreateRequest):
    store = get_prior_store(request)
    path = _normalize_path(body.path)
    if not path:
        raise HTTPException(status_code=400, detail="Folder path is required")
    try:
        result = store.create_folder(path)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    publish("folder_created", {"path": path, "revision": None})
    logger.info("Created prior folder '%s'", path)
    return {"status": "created", **result}


@router.put("/priors/folders")
def move_folder(request: Request, body: FolderMoveRequest):
    store = get_prior_store(request)
    path = _normalize_path(body.path)
    new_path = _normalize_path(body.new_path)
    if not path or not new_path:
        raise HTTPException(status_code=400, detail="Both path and new_path are required")
    active_affected = _folder_contains_active_priors(store, path)

    try:
        result = store.move_folder(path, new_path)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    revision = None
    if active_affected:
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish("folder_moved", {"path": path, "new_path": new_path, "revision": revision})
    logger.info("Moved prior folder '%s' -> '%s'", path, new_path)
    return {"status": "updated", "path": path, "new_path": new_path}


@router.post("/priors/folders/delete")
def delete_folder(request: Request, body: FolderDeleteRequest):
    store = get_prior_store(request)
    path = _normalize_path(body.path)
    if not path:
        raise HTTPException(status_code=400, detail="Folder path is required")
    active_affected = _folder_contains_active_priors(store, path)
    if not store.delete_folder(path):
        raise HTTPException(status_code=404, detail="Folder not found")
    revision = None
    if active_affected:
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish("folder_deleted", {"path": path, "revision": revision})
    logger.info("Deleted prior folder '%s'", path)
    return {"status": "deleted", "path": path}


@router.post("/priors/items/copy")
def copy_items(request: Request, body: PriorItemsCopyRequest):
    store = get_prior_store(request)
    destination_path = _normalize_path(body.destination_path)
    items = _normalize_item_refs(body.items)
    if not items:
        raise HTTPException(status_code=400, detail="At least one item is required")
    active_affected = (not body.as_draft) and _items_affect_active_world(store, items)

    copied_items: list[dict] = []
    for item in items:
        if item.kind == "prior":
            copied = store.copy_prior(item.id or "", destination_path, as_draft=body.as_draft)
            if copied is None:
                raise HTTPException(status_code=404, detail=f"Prior '{item.id}' not found")
            copied_items.append(_copied_item_payload(copied, "prior"))
            continue
        copied = store.copy_folder(item.path or "", destination_path, as_draft=body.as_draft)
        if copied is None:
            raise HTTPException(status_code=404, detail=f"Folder '{item.path}' not found")
        copied_items.append(_copied_item_payload(copied, "folder"))

    revision = None
    if active_affected:
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish("items_copied", {"count": len(copied_items), "revision": revision})
    logger.info("Copied %s prior items into '%s'%s", len(copied_items), destination_path, " as drafts" if body.as_draft else "")
    return {"status": "copied", "items": copied_items, "count": len(copied_items)}


@router.post("/priors/drafts")
def create_prior_draft(request: Request, prior: PriorDraftCreate):
    store = get_prior_store(request)
    path = _normalize_path(prior.path)
    prior_id = str(uuid.uuid4())[:8]
    result = store.create(
        prior_id,
        prior.name,
        "",
        prior.content,
        path,
        status="draft",
        validation_metadata=None,
    )
    publish("prior_created", {"id": prior_id, "path": path, "status": "draft"})
    logger.info("Created draft prior %s at '%s'", prior_id, path)
    return {"status": "created", **result}


@router.post("/priors/items/move")
def move_items(request: Request, body: PriorItemsMoveRequest):
    store = get_prior_store(request)
    destination_path = _normalize_path(body.destination_path)
    items = _normalize_item_refs(body.items)
    if not items:
        raise HTTPException(status_code=400, detail="At least one item is required")
    active_affected = _items_affect_active_world(store, items)

    moved_items: list[dict] = []
    try:
        for item in items:
            if item.kind == "prior":
                result = store.move_lessons([item.id or ""], destination_path)
                if result["moved_count"] == 0:
                    raise HTTPException(status_code=404, detail=f"Prior '{item.id}' not found")
                moved = store.get(item.id or "")
                if moved:
                    moved_items.append(_copied_item_payload(moved, "prior"))
                continue

            moved = store.move_folder_to(item.path or "", destination_path)
            if moved is None:
                raise HTTPException(status_code=404, detail=f"Folder '{item.path}' not found")
            moved_items.append(_copied_item_payload(moved, "folder"))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    revision = None
    if active_affected:
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish("items_moved", {"count": len(moved_items), "revision": revision})
    logger.info("Moved %s prior items into '%s'", len(moved_items), destination_path)
    return {"status": "moved", "items": moved_items, "count": len(moved_items)}


@router.post("/priors/items/delete")
def delete_items(request: Request, body: PriorItemsDeleteRequest):
    store = get_prior_store(request)
    items = _normalize_item_refs(body.items)
    if not items:
        raise HTTPException(status_code=400, detail="At least one item is required")
    active_affected = _items_affect_active_world(store, items)

    deleted_priors = 0
    deleted_folders = 0
    folder_items = sorted(
        [item for item in items if item.kind == "folder"],
        key=lambda item: len((_normalize_path(item.path or "")).split("/")),
        reverse=True,
    )
    prior_items = [item for item in items if item.kind == "prior"]

    for item in prior_items:
        deleted_priors += int(store.delete(item.id or ""))
    for item in folder_items:
        deleted_folders += int(store.delete_folder(item.path or ""))

    deleted = deleted_priors + deleted_folders

    if deleted == 0:
        raise HTTPException(status_code=404, detail="No matching priors or folders found")

    revision = None
    if active_affected:
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish(
        "items_deleted",
        {
            "count": deleted,
            "prior_count": deleted_priors,
            "folder_count": deleted_folders,
            "revision": revision,
        },
    )
    logger.info(
        "Deleted %s prior items (%s priors, %s folders)",
        deleted,
        deleted_priors,
        deleted_folders,
    )
    return {"status": "deleted", "count": deleted}


@router.post("/priors")
async def create_prior(
    request: Request,
    prior: PriorCreate,
    force: bool = Query(default=False),
):
    store = get_prior_store(request)
    prior.path = _normalize_path(prior.path)
    summary_for_validation = (prior.summary or "").strip() or fallback_prior_summary(
        name=prior.name,
        content=prior.content,
    )

    existing_priors = _active_only(store.list_all(path=prior.path, include_content=not force))
    duplicates = [existing for existing in existing_priors if existing.get("name") == prior.name]
    if duplicates:
        duplicate_ids = [existing["id"] for existing in duplicates]
        return {
            "status": "rejected",
            "reason": (
                f"A prior named '{prior.name}' already exists at path '{prior.path}' "
                f"(id: {', '.join(duplicate_ids)}). Update the existing prior instead."
            ),
            "conflicting_prior_ids": duplicate_ids,
            "hint": f"Use PUT /priors/{duplicate_ids[0]} to update the existing prior, or choose a different name.",
        }

    validation_feedback = None
    validation_metadata = None
    if not force:
        folder_tree = build_folder_tree_summary(store)
        validation = await validate_prior(
            name=prior.name,
            summary=summary_for_validation,
            content=prior.content,
            path=prior.path,
            existing_priors=existing_priors,
            folder_tree_summary=folder_tree,
        )
        validation_feedback = _validation_to_feedback(validation)
        validation_metadata = validation_feedback
        if not validation.approved:
            return {
                "status": "rejected",
                "reason": validation.feedback,
                "validation": validation_feedback,
                "conflicting_prior_ids": validation.conflicting_prior_ids,
                "hint": "Use force=true query parameter to skip validation",
            }

    persisted_summary = (prior.summary or "").strip()
    if not persisted_summary:
        persisted_summary = await generate_prior_summary(
            name=prior.name,
            content=prior.content,
            path=prior.path,
        )

    prior_id = str(uuid.uuid4())[:8]
    result = store.create(
        prior_id,
        prior.name,
        persisted_summary,
        prior.content,
        prior.path,
        status="active",
        creation_trace_id=prior.creation_trace_id,
        trace_source=prior.trace_source,
        validation_metadata=validation_metadata,
    )
    _clear_scope_prefix_cache_for_request(request)
    scope = store.bump_scope_revision()
    publish("prior_created", {"id": prior_id, "path": prior.path, "revision": scope["revision"]})
    logger.info("Created prior %s at '%s'", prior_id, prior.path)
    return {
        "status": "created",
        **result,
        "validation": validation_feedback,
    }


@router.post("/priors/{prior_id}/submit")
async def submit_prior(
    request: Request,
    prior_id: str,
    submission: PriorSubmitRequest,
    force: bool = Query(default=False),
):
    store = get_prior_store(request)
    existing = store.get(prior_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Prior not found")
    if existing.get("prior_status", "active") != "draft":
        raise HTTPException(status_code=400, detail="Only draft priors can be submitted")

    name = submission.name if submission.name is not None else existing["name"]
    content = submission.content if submission.content is not None else existing["content"]
    result_path = _normalize_path(submission.path) if submission.path is not None else existing["path"]

    active_priors = _active_only(store.list_all(path=result_path, include_content=not force))
    duplicates = [prior for prior in active_priors if prior.get("name") == name and prior.get("id") != prior_id]
    if duplicates:
        duplicate_ids = [prior["id"] for prior in duplicates]
        rejection_feedback = {
            "feedback": (
                f"A prior named '{name}' already exists at path '{result_path}' "
                f"(id: {', '.join(duplicate_ids)}). Choose a different name or update the existing active prior."
            ),
            "severity": "error",
            "conflicting_prior_ids": duplicate_ids,
        }
        result = store.update(
            prior_id,
            name,
            existing.get("summary", ""),
            content,
            path=result_path,
            status="draft",
            validation_metadata=rejection_feedback,
        )
        return {
            "status": "rejected",
            **(result or {}),
            "reason": rejection_feedback["feedback"],
            "validation": rejection_feedback,
            "conflicting_prior_ids": duplicate_ids,
            "hint": "Choose a different name or update the existing active prior instead.",
        }

    validation_feedback = None
    validation_metadata = None
    if not force:
        folder_tree = build_folder_tree_summary(store)
        validation = await validate_prior(
            name=name,
            summary=fallback_prior_summary(name=name, content=content),
            content=content,
            path=result_path,
            existing_priors=active_priors,
            existing_prior_id=prior_id,
            folder_tree_summary=folder_tree,
        )
        validation_feedback = _validation_to_feedback(validation)
        validation_metadata = validation_feedback
        if not validation.approved:
            result = store.update(
                prior_id,
                name,
                existing.get("summary", ""),
                content,
                path=result_path,
                status="draft",
                validation_metadata=validation_feedback,
            )
            return {
                "status": "rejected",
                **(result or {}),
                "reason": validation.feedback,
                "validation": validation_feedback,
                "conflicting_prior_ids": validation.conflicting_prior_ids,
                "hint": "Address the validation feedback and submit again.",
            }

    persisted_summary = await generate_prior_summary(
        name=name,
        content=content,
        path=result_path,
    )
    result = store.update(
        prior_id,
        name,
        persisted_summary,
        content,
        path=result_path,
        status="active",
        validation_metadata=validation_metadata,
    )
    _clear_scope_prefix_cache_for_request(request)
    scope = store.bump_scope_revision()
    publish("prior_updated", {"id": prior_id, "path": result_path, "revision": scope["revision"]})
    logger.info("Submitted draft prior %s", prior_id)
    return {
        "status": "submitted",
        **(result or {}),
        "validation": validation_feedback,
    }


@router.put("/priors/{prior_id}")
async def update_prior(
    request: Request,
    prior_id: str,
    update: PriorUpdate,
    force: bool = Query(default=False),
):
    store = get_prior_store(request)
    existing = store.get(prior_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Prior not found")

    existing_status = existing.get("prior_status", "active")
    name = update.name if update.name is not None else existing["name"]
    content = update.content if update.content is not None else existing["content"]
    result_path = _normalize_path(update.path) if update.path is not None else existing["path"]
    content_changed = update.content is not None and update.content != existing["content"]
    summary_for_validation = (
        update.summary.strip()
        if update.summary is not None
        else existing["summary"]
    ) or fallback_prior_summary(name=name, content=content)

    validation_feedback = None
    validation_metadata = existing.get("validation_metadata")
    if content_changed and existing_status == "active" and not force:
        existing_with_content = _active_only(store.list_all(path=result_path, include_content=True))
        folder_tree = build_folder_tree_summary(store)
        validation = await validate_prior(
            name=name,
            summary=summary_for_validation,
            content=content,
            path=result_path,
            existing_priors=existing_with_content,
            existing_prior_id=prior_id,
            folder_tree_summary=folder_tree,
        )
        validation_feedback = _validation_to_feedback(validation)
        validation_metadata = validation_feedback
        if not validation.approved:
            return {
                "status": "rejected",
                "reason": validation.feedback,
                "validation": validation_feedback,
                "conflicting_prior_ids": validation.conflicting_prior_ids,
                "hint": "Use force=true query parameter to skip validation",
            }

    if update.summary is not None:
        persisted_summary = update.summary.strip()
    elif content_changed and existing_status == "active":
        persisted_summary = await generate_prior_summary(
            name=name,
            content=content,
            path=result_path,
        )
    else:
        persisted_summary = existing["summary"]

    result = store.update(
        prior_id,
        name,
        persisted_summary,
        content,
        path=result_path if update.path is not None else None,
        status=existing_status,
        validation_metadata=validation_metadata,
    )
    revision = None
    if existing_status == "active":
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish("prior_updated", {"id": prior_id, "path": result_path, "revision": revision})
    logger.info("Updated prior %s", prior_id)
    return {
        "status": "updated",
        **(result or {}),
        "validation": validation_feedback,
    }


@router.delete("/priors/{prior_id}")
def delete_prior(request: Request, prior_id: str):
    store = get_prior_store(request)
    existing = store.get(prior_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Prior not found")
    if not store.delete(prior_id):
        raise HTTPException(status_code=404, detail="Prior not found")
    revision = None
    if existing.get("prior_status", "active") == "active":
        _clear_scope_prefix_cache_for_request(request)
        scope = store.bump_scope_revision()
        revision = scope["revision"]
    publish("prior_deleted", {"id": prior_id, "revision": revision})
    logger.info("Deleted prior %s", prior_id)
    return {"status": "deleted", "id": prior_id}


@router.post("/priors/retrieve", response_model=PriorRetrieveResponse)
async def retrieve_priors_endpoint(request: Request, body: PriorRetrieveRequest):
    store = get_prior_store(request)
    base_path = _normalize_path(body.base_path)
    if body.base_path and not store.folder_exists(base_path):
        raise HTTPException(status_code=404, detail="Folder not found")
    scope = store.read_scope_metadata()
    priors_revision = int(scope["revision"])
    requested_model = body.model or "openai/gpt-5.4"
    model_used = resolve_model(requested_model, "cheap")
    ignore_ids = sorted({prior_id for prior_id in body.ignore_prior_ids if prior_id}) if body.ignore_prior_ids else []

    logger.info(
        "[PRIORS ROUTE] retrieve start user=%s project=%s revision=%s base_path=%s requested_model=%s resolved_model=%s ignore_ids=%s\n"
        "[PRIORS ROUTE] context (%d chars):\n%s",
        scope["user_id"],
        scope["project_id"],
        priors_revision,
        base_path or "(root)",
        requested_model,
        model_used,
        ignore_ids,
        len(body.context or ""),
        body.context or "(empty)",
    )

    cached = get_cached_retrieval(
        user_id=str(scope["user_id"]),
        project_id=str(scope["project_id"]),
        priors_revision=priors_revision,
        base_path=base_path,
        model=model_used,
        context=body.context,
        ignore_prior_ids=body.ignore_prior_ids,
    )
    if cached is not None:
        logger.info(
            "[PRIORS ROUTE] cache hit revision=%s base_path=%s requested_model=%s resolved_model=%s prior_count=%s ids=%s",
            priors_revision,
            base_path or "(root)",
            requested_model,
            model_used,
            cached.get("prior_count"),
            [prior.get("id") for prior in cached.get("priors", [])],
        )
        return PriorRetrieveResponse(**cached)

    logger.info(
        "[PRIORS ROUTE] cache miss revision=%s base_path=%s requested_model=%s resolved_model=%s",
        priors_revision,
        base_path or "(root)",
        requested_model,
        model_used,
    )

    retrieve_task = asyncio.create_task(
        retrieve_relevant_priors(
            store=store,
            context=body.context,
            base_path=base_path,
            model=requested_model,
            ignore_prior_ids=body.ignore_prior_ids,
        )
    )

    async def _wait_disconnect():
        while not await request.is_disconnected():
            await asyncio.sleep(1)

    disconnect_task = asyncio.create_task(_wait_disconnect())

    done, pending = await asyncio.wait(
        [retrieve_task, disconnect_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    if disconnect_task in done:
        logger.info("Client disconnected during priors retrieval, cancelled LLM calls")
        raise asyncio.CancelledError()

    priors = retrieve_task.result()
    response = PriorRetrieveResponse(
        context=body.context,
        base_path=base_path,
        priors=[
            RetrievedPrior(**{key: prior[key] for key in ("id", "name", "summary", "content", "path")})
            for prior in priors
        ],
        prior_count=len(priors),
        priors_revision=priors_revision,
        rendered_priors_block=_build_injected_context(priors),
        model_used=model_used,
    )
    logger.info(
        "[PRIORS ROUTE] retrieve complete prior_count=%s ids=%s rendered_block_chars=%d",
        response.prior_count,
        [prior.id for prior in response.priors],
        len(response.rendered_priors_block),
    )
    store_cached_retrieval(
        user_id=str(scope["user_id"]),
        project_id=str(scope["project_id"]),
        priors_revision=priors_revision,
        base_path=base_path,
        model=model_used,
        context=body.context,
        ignore_prior_ids=body.ignore_prior_ids,
        response=response.model_dump(),
    )
    return response
