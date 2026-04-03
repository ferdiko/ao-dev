class UsersMixin:
    def get_user(self, user_id):
        return self.backend.get_user_query(user_id)

    def upsert_user(self, user_id, full_name, email):
        self.backend.upsert_user_query(user_id, full_name, email)

    def update_user_llm_settings(self, user_id, llm_settings):
        from sovara.server.llm_settings import flatten_user_llm_settings

        self.backend.update_user_llm_settings_query(
            user_id,
            flatten_user_llm_settings(llm_settings),
        )

    def delete_user(self, user_id):
        self.backend.delete_user_query(user_id)
