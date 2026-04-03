class PriorsMixin:
    def get_priors_applied_for_run(self, run_id):
        rows = self.backend.get_priors_applied_for_run_query(run_id)
        return [
            {
                "prior_id": row["prior_id"],
                "run_id": row["run_id"],
                "node_uuid": row["node_uuid"],
                "name": row["name"] or "Unknown Run",
            }
            for row in rows
        ]

    def get_runs_for_prior(self, prior_id):
        rows = self.backend.get_priors_applied_query(prior_id)
        return [
            {
                "runId": row["run_id"],
                "nodeUuid": row["node_uuid"],
                "name": row["name"] or "Unknown Run",
            }
            for row in rows
        ]

    def add_prior_applied(self, prior_id, run_id, node_uuid=None):
        self.backend.add_prior_applied_query(prior_id, run_id, node_uuid)

    def remove_prior_applied(self, prior_id, run_id, node_uuid=None):
        self.backend.remove_prior_applied_query(prior_id, run_id, node_uuid)

    def delete_priors_applied_for_prior(self, prior_id):
        self.backend.delete_priors_applied_for_prior_query(prior_id)
