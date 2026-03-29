"""Client for the in-repo priors backend child service."""

from __future__ import annotations

from typing import Any

import httpx

from sovara.common.constants import PRIORS_SERVER_URL


class PriorsBackendError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class PriorsBackendClient:
    def __init__(self, user_id: str, project_id: str):
        self.user_id = user_id
        self.project_id = project_id

    def _headers(self) -> dict[str, str]:
        return {
            "x-sovara-user-id": self.user_id,
            "x-sovara-project-id": self.project_id,
        }

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any = None) -> Any:
        try:
            with httpx.Client(base_url=PRIORS_SERVER_URL, timeout=35.0, headers=self._headers()) as client:
                response = client.request(method, path, params=params, json=json_body)
        except httpx.HTTPError as exc:
            raise PriorsBackendError(
                f"Unable to reach priors backend at {PRIORS_SERVER_URL}: {exc}",
                status_code=502,
            ) from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                detail = payload.get("detail")
                if isinstance(detail, dict):
                    message = detail.get("error") or str(detail)
                else:
                    message = payload.get("error") or detail or response.text
            else:
                message = response.text
            raise PriorsBackendError(message or "Priors backend error", status_code=response.status_code)
        try:
            return response.json()
        except ValueError:
            return {}

    def get_scope(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/priors/scope")

    def list_priors(self, *, path: str | None = None) -> dict[str, Any]:
        params = {"path": path} if path is not None else None
        return self._request("GET", "/api/v1/priors", params=params)

    def get_prior(self, prior_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/priors/{prior_id}")

    def create_prior(self, body: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        return self._request("POST", "/api/v1/priors", params={"force": str(force).lower()}, json_body=body)

    def create_draft_prior(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/priors/drafts", json_body=body)

    def update_prior(self, prior_id: str, body: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/priors/{prior_id}", params={"force": str(force).lower()}, json_body=body)

    def submit_prior(self, prior_id: str, body: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/priors/{prior_id}/submit", params={"force": str(force).lower()}, json_body=body)

    def delete_prior(self, prior_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v1/priors/{prior_id}")

    def folder_ls(self, path: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/priors/folders/ls", json_body={"path": path})

    def create_folder(self, path: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/priors/folders", json_body={"path": path})

    def move_folder(self, path: str, new_path: str) -> dict[str, Any]:
        return self._request("PUT", "/api/v1/priors/folders", json_body={"path": path, "new_path": new_path})

    def delete_folder(self, path: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/priors/folders/delete", json_body={"path": path})

    def copy_items(self, items: list[dict[str, Any]], destination_path: str, *, as_draft: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/priors/items/copy",
            json_body={"items": items, "destination_path": destination_path, "as_draft": as_draft},
        )

    def move_items(self, items: list[dict[str, Any]], destination_path: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/priors/items/move",
            json_body={"items": items, "destination_path": destination_path},
        )

    def delete_items(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/priors/items/delete",
            json_body={"items": items},
        )

    def query_priors(self, path: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/api/v1/query/priors", json_body={"path": path})

    def retrieve_priors(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/priors/retrieve", json_body=body)
