"""Project-related UI routes."""

import os
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sovara.common.project import (
    delete_project_configs,
    find_project_root,
    read_project_id,
    write_project_id,
)
from sovara.common.user import read_user_id
from sovara.server.app import get_state
from sovara.server.database_manager import DB
from sovara.server.state import ServerState

router = APIRouter()

TAG_COLORS = {
    "#0969da",
    "#1a7f37",
    "#cf222e",
    "#bf8700",
    "#8250df",
    "#e85aad",
    "#0598d5",
    "#d1570a",
    "#5e60ce",
    "#1b8a72",
}


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    location: str


class UpdateProjectLocationRequest(BaseModel):
    project_id: str
    old_location: str
    new_location: str


class DeleteProjectLocationRequest(BaseModel):
    project_id: str
    location: str


class UpdateProjectRequest(BaseModel):
    project_id: str
    name: str
    description: str = ""


class DeleteProjectRequest(BaseModel):
    project_id: str
    confirmation_name: str


class CreateProjectTagRequest(BaseModel):
    name: str
    color: str


class DeleteProjectTagRequest(BaseModel):
    tag_id: str


@router.post("/pick-directory")
def pick_directory():
    """Open native OS folder picker and return the selected path."""
    import subprocess
    import sys

    path = None
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select Project Location")'],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                path = result.stdout.strip().rstrip("/")
        elif sys.platform == "win32":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip()
        else:
            for cmd in [
                ["zenity", "--file-selection", "--directory", "--title=Select Project Location"],
                ["kdialog", "--getexistingdirectory", "."],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if result.returncode == 0 and result.stdout.strip():
                        path = result.stdout.strip()
                        break
                except FileNotFoundError:
                    continue
    except subprocess.TimeoutExpired:
        pass

    return {"path": path}


@router.post("/create-project")
def create_project(req: CreateProjectRequest):
    """Create a new project with validation."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=403, content={
            "error": "No user configured. Run so-record once to set up your user profile."
        })

    location = os.path.abspath(req.location)

    if not os.path.isdir(location):
        return JSONResponse(status_code=400, content={"error": f"Directory does not exist: {location}"})

    for project in DB.get_all_projects():
        if project["name"] == req.name:
            return JSONResponse(
                status_code=409,
                content={"error": f"A project named '{req.name}' already exists."},
            )

    project_root = find_project_root(location)
    if project_root:
        existing_id = read_project_id(project_root)
        existing = DB.get_project(existing_id)
        name = existing["name"] if existing else existing_id
        return JSONResponse(status_code=409, content={
            "error": f"This directory is already part of project '{name}' (root: {project_root})."
        })

    project_id = str(uuid.uuid4())
    write_project_id(location, project_id)
    DB.upsert_project(project_id, req.name, req.description)
    DB.upsert_project_location(user_id, project_id, location)

    return {"project_id": project_id, "name": req.name}


@router.post("/update-project-location")
def update_project_location(req: UpdateProjectLocationRequest):
    """Update a project location (e.g. after moving the project folder)."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=403, content={"error": "No user configured."})

    new_location = os.path.abspath(req.new_location)
    if not os.path.isdir(new_location):
        return JSONResponse(status_code=400, content={"error": f"Directory does not exist: {new_location}"})

    write_project_id(new_location, req.project_id)
    DB.delete_project_location(user_id, req.project_id, req.old_location)
    DB.upsert_project_location(user_id, req.project_id, new_location)

    return {"ok": True}


@router.post("/update-project")
def update_project(req: UpdateProjectRequest, state: ServerState = Depends(get_state)):
    """Update project name and description."""
    project = DB.get_project(req.project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    if not req.name.strip():
        return JSONResponse(status_code=400, content={"error": "Project name is required."})
    for project_row in DB.get_all_projects():
        if project_row["name"] == req.name.strip() and project_row["project_id"] != req.project_id:
            return JSONResponse(
                status_code=409,
                content={"error": f"A project named '{req.name.strip()}' already exists."},
            )
    DB.upsert_project(req.project_id, req.name.strip(), req.description.strip())
    state.notify_project_list_changed()
    return {
        "project": {
            "project_id": req.project_id,
            "name": req.name.strip(),
            "description": req.description.strip(),
        }
    }


@router.post("/delete-project-location")
def delete_project_location(req: DeleteProjectLocationRequest):
    """Remove a single project location."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=403, content={"error": "No user configured."})
    DB.delete_project_location(user_id, req.project_id, req.location)
    delete_project_configs([req.location])
    return {"ok": True}


@router.post("/delete-project")
def delete_project(req: DeleteProjectRequest, state: ServerState = Depends(get_state)):
    """Delete an entire project and all associated data."""
    project = DB.get_project(req.project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    if req.confirmation_name != project["name"]:
        return JSONResponse(status_code=400, content={"error": "Name does not match."})
    locations = DB.get_all_project_locations(req.project_id)
    delete_project_configs([row["project_location"] for row in locations])
    DB.delete_project(req.project_id)
    state.notify_run_list_changed()
    state.notify_project_list_changed()
    return {"ok": True}


def _validate_location(path: str, expected_project_id: str) -> bool:
    """Check if a location is valid: directory exists and .sovara/.project_id matches."""
    if not os.path.isdir(path):
        return False
    project_root = find_project_root(path)
    if not project_root:
        return False
    try:
        return read_project_id(project_root) == expected_project_id
    except Exception:
        return False


@router.get("/projects")
def get_projects(state: ServerState = Depends(get_state)):
    """List all projects with run counts and location sync status."""
    projects = DB.get_all_projects()
    result = []
    for project in projects:
        project_id = project["project_id"]
        run_count = DB.get_run_count(project_id=project_id)
        location_rows = DB.get_all_project_locations(project_id)
        locations = []
        location_warning = False
        for row in location_rows:
            path = row["project_location"]
            valid = _validate_location(path, project_id)
            locations.append({"path": path, "valid": valid})
            if not valid:
                location_warning = True
        result.append({
            "project_id": project_id,
            "name": project["name"],
            "description": project["description"] or "",
            "created_at": project["created_at"],
            "last_run_at": project["last_run_at"],
            "num_runs": run_count,
            "num_users": DB.get_project_user_count(project_id),
            "locations": locations,
            "location_warning": location_warning,
        })
    return {"projects": result}


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    """Get a single project by ID."""
    project = DB.get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "description": project["description"] or "",
    }


@router.get("/projects/{project_id}/tags")
def get_project_tags(project_id: str):
    project = DB.get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    return {"tags": DB.get_project_tags(project_id)}


@router.post("/projects/{project_id}/tags")
def create_project_tag(project_id: str, req: CreateProjectTagRequest, state: ServerState = Depends(get_state)):
    if req.color not in TAG_COLORS:
        return JSONResponse(status_code=400, content={"error": "Invalid tag color."})
    try:
        tag = DB.create_project_tag(project_id, req.name.strip(), req.color)
    except ValueError as exc:
        message = str(exc)
        if "already exists" in message:
            status_code = 409
        elif "Project not found" in message:
            status_code = 404
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"error": message})
    state.notify_run_list_changed()
    return {"tag": tag}


@router.post("/projects/{project_id}/tags/delete")
def delete_project_tag(project_id: str, req: DeleteProjectTagRequest, state: ServerState = Depends(get_state)):
    try:
        DB.delete_project_tag(project_id, req.tag_id)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return JSONResponse(status_code=status_code, content={"error": message})
    state.notify_run_list_changed()
    return {"ok": True}
