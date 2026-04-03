import os
import uuid


class ProjectsMixin:
    @staticmethod
    def _normalize_tag_row(row):
        return {
            "tag_id": row["tag_id"],
            "name": row["name"],
            "color": row["color"],
        }

    def get_project_tags(self, project_id):
        rows = self.backend.get_project_tags_query(project_id)
        return [self._normalize_tag_row(row) for row in rows]

    def create_project_tag(self, project_id, name, color):
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found.")

        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("Tag name is required.")

        if self.backend.get_project_tag_by_name_query(project_id, normalized_name):
            raise ValueError("A tag with this name already exists in the project.")

        tag_id = str(uuid.uuid4())
        self.backend.insert_project_tag_query(tag_id, project_id, normalized_name, color)
        return self._normalize_tag_row(self.backend.get_project_tag_query(tag_id))

    def delete_project_tag(self, project_id, tag_id):
        row = self.backend.get_project_tag_query(tag_id)
        if row is None or row["project_id"] != project_id:
            raise ValueError("Tag not found.")
        self.backend.delete_project_tag_query(project_id, tag_id)

    def replace_run_tags(self, run_id, tag_ids):
        context = self.backend.get_run_tag_context_query(run_id)
        if context is None:
            raise ValueError("Run not found.")

        project_id = context["project_id"]
        if not project_id:
            raise ValueError("Tags can only be assigned to project-scoped runs.")

        unique_tag_ids = list(dict.fromkeys(tag_ids))
        if unique_tag_ids:
            project_tags = self.backend.get_project_tags_by_ids_query(project_id, unique_tag_ids)
            if len(project_tags) != len(unique_tag_ids):
                raise ValueError("All tags must belong to the run's project.")

        self.backend.replace_run_tags_query(run_id, unique_tag_ids)
        return self._get_tags_for_runs_map([run_id]).get(run_id, [])

    def get_project(self, project_id):
        return self.backend.get_project_query(project_id)

    def upsert_project(self, project_id, name, description):
        self.backend.upsert_project_query(project_id, name, description)

    def update_project_last_run_at(self, project_id):
        self.backend.update_project_last_run_at_query(project_id)

    def get_all_projects(self):
        return self.backend.get_all_projects_query(user_id=self.user_id)

    def get_project_user_count(self, project_id):
        return self.backend.get_project_user_count_query(project_id)

    def delete_project(self, project_id):
        self.backend.delete_project_query(project_id)

    def upsert_project_location(self, user_id, project_id, project_location):
        self.backend.upsert_project_location_query(user_id, project_id, project_location)

    def find_project_for_location(self, user_id, path):
        """Find a project whose known location is an ancestor of (or equal to) the given path."""
        rows = self.backend.get_project_at_location_query(user_id, path)
        path = os.path.abspath(path) + os.sep
        for row in rows:
            loc = os.path.abspath(row["project_location"]) + os.sep
            if path.startswith(loc):
                return row["project_id"], row["project_location"]
        return None

    def get_user_project_locations(self, user_id):
        """Get all project locations for a user across all projects."""
        rows = self.backend.query_all(
            "SELECT project_location FROM user_project_locations WHERE user_id=?",
            (user_id,),
        )
        return [row["project_location"] for row in rows]

    def get_project_locations(self, user_id, project_id):
        return self.backend.get_project_locations_query(user_id, project_id)

    def get_all_project_locations(self, project_id):
        return self.backend.get_all_project_locations_query(project_id)

    def delete_project_location(self, user_id, project_id, project_location):
        self.backend.delete_project_location_query(user_id, project_id, project_location)
