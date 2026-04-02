"""Scoped file-backed storage for priors."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

from sovara.server.priors_backend.constants import PRIORS_BACKEND_HOME, SCOPE_METADATA_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str) -> str:
    cleaned = (path or "").strip("/")
    return f"{cleaned}/" if cleaned else ""


class PriorStore:
    """Filesystem-backed priors store scoped by user and project."""

    _TRACE_FIELDS = (
        "creation_trace_id",
        "trace_source",
        "created_at",
        "updated_at",
        "validation_metadata",
    )

    def __init__(self, user_id: str, project_id: str):
        if not user_id:
            raise ValueError("user_id is required")
        if not project_id:
            raise ValueError("project_id is required")

        self.user_id = user_id
        self.project_id = project_id
        self.base = os.path.join(PRIORS_BACKEND_HOME, user_id, project_id)
        os.makedirs(self.base, exist_ok=True)
        self._ensure_scope_metadata()

    @property
    def scope_metadata_path(self) -> str:
        return os.path.join(self.base, SCOPE_METADATA_FILENAME)

    def _ensure_scope_metadata(self) -> dict:
        if os.path.exists(self.scope_metadata_path):
            return self.read_scope_metadata()
        data = {
            "user_id": self.user_id,
            "project_id": self.project_id,
            "revision": 1,
            "updated_at": _utc_now_iso(),
        }
        self._write_scope_metadata(data)
        return data

    def _write_scope_metadata(self, data: dict) -> None:
        os.makedirs(self.base, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.base, suffix=".scope.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.scope_metadata_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def read_scope_metadata(self) -> dict:
        with open(self.scope_metadata_path, encoding="utf-8") as handle:
            return json.load(handle)

    def bump_scope_revision(self) -> dict:
        data = self.read_scope_metadata()
        data["revision"] = int(data.get("revision", 0)) + 1
        data["updated_at"] = _utc_now_iso()
        self._write_scope_metadata(data)
        return data

    def _prior_path(self, path: str, prior_id: str) -> str:
        return os.path.join(self.base, _normalize_path(path), f"{prior_id}.json")

    def _folder_path(self, path: str) -> str:
        return os.path.join(self.base, _normalize_path(path))

    def folder_exists(self, path: str) -> bool:
        normalized = _normalize_path(path)
        if not normalized:
            return True
        return os.path.isdir(self._folder_path(normalized))

    def _join_folder_path(self, parent_path: str, name: str) -> str:
        parent = _normalize_path(parent_path)
        segment = name.strip("/").strip()
        return _normalize_path(f"{parent}{segment}" if parent else segment)

    def _folder_name(self, path: str) -> str:
        normalized = _normalize_path(path)
        return normalized.rstrip("/").split("/")[-1] if normalized else ""

    def _read_prior_file(self, filepath: str) -> dict:
        with open(filepath, encoding="utf-8") as handle:
            return json.load(handle)

    def _write_prior_file(
        self,
        filepath: str,
        prior_id: str,
        name: str,
        summary: str,
        content: str,
        **extra,
    ) -> None:
        dirpath = os.path.dirname(filepath)
        os.makedirs(dirpath, exist_ok=True)
        data = {
            "prior_id": prior_id,
            "name": name,
            "summary": summary,
            "content": content,
        }
        data.update(extra)
        fd, tmp = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, filepath)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _find_prior_file(self, prior_id: str) -> Optional[str]:
        target = f"{prior_id}.json"
        for dirpath, _, filenames in os.walk(self.base):
            if target in filenames:
                return os.path.join(dirpath, target)
        return None

    def _relative_path_from_file(self, filepath: str) -> str:
        rel = os.path.relpath(os.path.dirname(filepath), self.base)
        if rel == ".":
            return ""
        return rel.replace(os.sep, "/") + "/"

    def _is_prior_file(self, filename: str) -> bool:
        return filename.endswith(".json")

    def _existing_prior_names(self, path: str, exclude_prior_id: Optional[str] = None) -> set[str]:
        target_dir = self._folder_path(path)
        if not os.path.isdir(target_dir):
            return set()
        names: set[str] = set()
        for entry in os.listdir(target_dir):
            full = os.path.join(target_dir, entry)
            if not os.path.isfile(full) or not self._is_prior_file(entry):
                continue
            data = self._read_prior_file(full)
            if exclude_prior_id and data.get("prior_id") == exclude_prior_id:
                continue
            names.add(str(data.get("name", "")))
        return names

    def _unique_prior_name(self, path: str, desired_name: str, exclude_prior_id: Optional[str] = None) -> str:
        existing = self._existing_prior_names(path, exclude_prior_id=exclude_prior_id)
        if desired_name not in existing:
            return desired_name
        base = desired_name
        suffix = " copy"
        candidate = f"{base}{suffix}"
        counter = 2
        while candidate in existing:
            candidate = f"{base}{suffix} {counter}"
            counter += 1
        return candidate

    def _unique_folder_path(self, parent_path: str, desired_name: str) -> str:
        candidate_name = desired_name
        candidate_path = self._join_folder_path(parent_path, candidate_name)
        if not os.path.exists(self._folder_path(candidate_path)):
            return candidate_path
        suffix = " copy"
        candidate_name = f"{desired_name}{suffix}"
        counter = 2
        candidate_path = self._join_folder_path(parent_path, candidate_name)
        while os.path.exists(self._folder_path(candidate_path)):
            candidate_name = f"{desired_name}{suffix} {counter}"
            candidate_path = self._join_folder_path(parent_path, candidate_name)
            counter += 1
        return candidate_path

    def _extract_trace_fields(self, data: dict) -> dict:
        return {k: data.get(k) for k in self._TRACE_FIELDS}

    def _build_prior_dict(self, data: dict, filepath: str, include_content: bool = True) -> dict:
        entry = {
            "id": data.get("prior_id", ""),
            "name": data.get("name", ""),
            "summary": data.get("summary", ""),
            "path": self._relative_path_from_file(filepath),
            **self._extract_trace_fields(data),
        }
        entry["prior_status"] = data.get("status", "active")
        if include_content:
            entry["content"] = data.get("content", "")
        return entry

    def create(
        self,
        prior_id: str,
        name: str,
        summary: str,
        content: str,
        path: str = "",
        status: str = "active",
        creation_trace_id: Optional[str] = None,
        trace_source: Optional[str] = None,
        validation_metadata: Optional[dict] = None,
    ) -> dict:
        now = _utc_now_iso()
        filepath = self._prior_path(path, prior_id)
        extra = {
            "status": status,
            "creation_trace_id": creation_trace_id,
            "trace_source": trace_source,
            "created_at": now,
            "updated_at": now,
            "validation_metadata": validation_metadata,
        }
        response_extra = {k: v for k, v in extra.items() if k != "status"}
        self._write_prior_file(filepath, prior_id, name, summary, content, **extra)
        return {
            "id": prior_id,
            "name": name,
            "summary": summary,
            "content": content,
            "path": _normalize_path(path),
            "prior_status": status,
            **response_extra,
        }

    def get(self, prior_id: str) -> Optional[dict]:
        filepath = self._find_prior_file(prior_id)
        if filepath is None:
            return None
        return self._build_prior_dict(self._read_prior_file(filepath), filepath, include_content=True)

    def list_all(self, path: Optional[str] = None, include_content: bool = False) -> list[dict]:
        search_dir = self.base if path is None else os.path.join(self.base, _normalize_path(path))
        if not os.path.isdir(search_dir):
            return []

        results: list[dict] = []
        for dirpath, _, filenames in os.walk(search_dir):
            for filename in filenames:
                if not self._is_prior_file(filename):
                    continue
                filepath = os.path.join(dirpath, filename)
                if os.path.basename(filepath) == SCOPE_METADATA_FILENAME:
                    continue
                data = self._read_prior_file(filepath)
                results.append(self._build_prior_dict(data, filepath, include_content=include_content))
        return results

    def list_folders(self, path: str = "", include_content: bool = False) -> dict:
        path = _normalize_path(path)
        target_dir = os.path.join(self.base, path) if path else self.base
        folders = []
        priors = []

        if not os.path.isdir(target_dir):
            return {"folders": [], "priors": [], "prior_count": 0}

        for entry in sorted(os.listdir(target_dir)):
            if entry == SCOPE_METADATA_FILENAME:
                continue
            full = os.path.join(target_dir, entry)
            if os.path.isdir(full):
                folders.append(
                    {
                        "path": path + entry + "/",
                        "prior_count": self._count_priors_recursive(full),
                    }
                )
            elif self._is_prior_file(entry):
                data = self._read_prior_file(full)
                priors.append(self._build_prior_dict(data, full, include_content=include_content))

        return {"folders": folders, "priors": priors, "prior_count": len(priors)}

    def _count_priors_recursive(self, directory: str) -> int:
        count = 0
        for root, _, files in os.walk(directory):
            count += sum(
                1
                for filename in files
                if self._is_prior_file(filename) and filename != SCOPE_METADATA_FILENAME
            )
        return count

    def create_folder(self, path: str) -> dict:
        folder_dir = self._folder_path(path)
        if os.path.exists(folder_dir):
            raise FileExistsError(f"Folder '{_normalize_path(path)}' already exists")
        os.makedirs(folder_dir, exist_ok=True)
        return {"path": _normalize_path(path)}

    def move_folder(self, path: str, new_path: str) -> Optional[dict]:
        source_path = _normalize_path(path)
        target_path = _normalize_path(new_path)
        if not source_path or not target_path:
            return None

        source_dir = os.path.normpath(self._folder_path(source_path))
        target_dir = os.path.normpath(self._folder_path(target_path))
        base = os.path.normpath(self.base)

        if not os.path.isdir(source_dir):
            return None
        if source_dir == target_dir:
            return {"path": target_path}
        if os.path.exists(target_dir):
            raise FileExistsError(f"Folder '{target_path}' already exists")
        if os.path.commonpath([source_dir, target_dir]) == source_dir:
            raise ValueError("Cannot move a folder into one of its descendants")
        if os.path.commonpath([base, target_dir]) != base:
            raise ValueError("Target path escapes priors root")

        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        shutil.move(source_dir, target_dir)
        return {"path": target_path}

    def move_folder_to(self, path: str, destination_parent: str) -> Optional[dict]:
        source_path = _normalize_path(path)
        destination_parent = _normalize_path(destination_parent)
        folder_name = self._folder_name(source_path)
        if not folder_name:
            return None
        target_path = self._join_folder_path(destination_parent, folder_name)
        return self.move_folder(source_path, target_path)

    def delete_folder(self, path: str) -> bool:
        target_path = _normalize_path(path)
        if not target_path:
            return False
        folder_dir = os.path.normpath(self._folder_path(target_path))
        if not os.path.isdir(folder_dir):
            return False
        shutil.rmtree(folder_dir)
        return True

    def update(
        self,
        prior_id: str,
        name: str,
        summary: str,
        content: str,
        path: Optional[str] = None,
        status: Optional[str] = None,
        validation_metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        old_filepath = self._find_prior_file(prior_id)
        if old_filepath is None:
            return None

        old_data = self._read_prior_file(old_filepath)
        current_path = self._relative_path_from_file(old_filepath)
        target_path = _normalize_path(path) if path is not None else current_path

        extra = {
            "status": status if status is not None else old_data.get("status", "active"),
            "creation_trace_id": old_data.get("creation_trace_id"),
            "trace_source": old_data.get("trace_source"),
            "created_at": old_data.get("created_at"),
            "updated_at": _utc_now_iso(),
            "validation_metadata": validation_metadata if validation_metadata is not None else old_data.get("validation_metadata"),
        }
        response_extra = {k: v for k, v in extra.items() if k != "status"}

        new_filepath = self._prior_path(target_path, prior_id)
        self._write_prior_file(new_filepath, prior_id, name, summary, content, **extra)
        if os.path.normpath(old_filepath) != os.path.normpath(new_filepath):
            os.remove(old_filepath)

        return {
            "id": prior_id,
            "name": name,
            "summary": summary,
            "content": content,
            "path": target_path,
            "prior_status": extra["status"],
            **response_extra,
        }

    def delete(self, prior_id: str) -> bool:
        filepath = self._find_prior_file(prior_id)
        if filepath is None:
            return False
        os.remove(filepath)
        return True

    def move_lessons(self, prior_ids: list[str], dst: str) -> dict:
        dst = _normalize_path(dst)
        moved = 0
        for prior_id in prior_ids:
            filepath = self._find_prior_file(prior_id)
            if filepath is None:
                continue
            new_filepath = self._prior_path(dst, prior_id)
            if os.path.normpath(filepath) == os.path.normpath(new_filepath):
                continue
            os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
            shutil.move(filepath, new_filepath)
            moved += 1
        return {"moved_count": moved}

    def copy_prior(self, prior_id: str, dst: str, *, as_draft: bool = False) -> Optional[dict]:
        filepath = self._find_prior_file(prior_id)
        if filepath is None:
            return None
        data = self._read_prior_file(filepath)
        new_id = str(uuid.uuid4())[:8]
        unique_name = self._unique_prior_name(dst, str(data.get("name", "")))
        return self.create(
            new_id,
            unique_name,
            str(data.get("summary", "")),
            str(data.get("content", "")),
            dst,
            status="draft" if as_draft else str(data.get("status", "active")),
            creation_trace_id=data.get("creation_trace_id"),
            trace_source=data.get("trace_source"),
            validation_metadata=None if as_draft else data.get("validation_metadata"),
        )

    def copy_folder(self, path: str, destination_parent: str, *, as_draft: bool = False) -> Optional[dict]:
        source_path = _normalize_path(path)
        destination_parent = _normalize_path(destination_parent)
        source_dir = os.path.normpath(self._folder_path(source_path))
        if not os.path.isdir(source_dir):
            return None

        folder_name = self._folder_name(source_path)
        if not folder_name:
            return None

        target_root_path = self._unique_folder_path(destination_parent, folder_name)
        target_root_dir = self._folder_path(target_root_path)
        os.makedirs(target_root_dir, exist_ok=True)

        for dirpath, _, filenames in os.walk(source_dir):
            rel_dir = os.path.relpath(dirpath, source_dir)
            relative_folder = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
            target_folder_path = self._join_folder_path(target_root_path, relative_folder.rstrip("/")) if relative_folder else target_root_path
            for filename in filenames:
                if filename == SCOPE_METADATA_FILENAME or not self._is_prior_file(filename):
                    continue
                filepath = os.path.join(dirpath, filename)
                data = self._read_prior_file(filepath)
                self.create(
                    str(uuid.uuid4())[:8],
                    str(data.get("name", "")),
                    str(data.get("summary", "")),
                    str(data.get("content", "")),
                    target_folder_path,
                    status="draft" if as_draft else str(data.get("status", "active")),
                    creation_trace_id=data.get("creation_trace_id"),
                    trace_source=data.get("trace_source"),
                    validation_metadata=None if as_draft else data.get("validation_metadata"),
                )

        return {"path": target_root_path}
