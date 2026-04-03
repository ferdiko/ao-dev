def init_db(conn):
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            llm_primary_provider TEXT,
            llm_primary_model_name TEXT,
            llm_primary_api_base TEXT,
            llm_helper_provider TEXT,
            llm_helper_model_name TEXT,
            llm_helper_api_base TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now'))
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now')),
            last_run_at TIMESTAMP
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            parent_run_id TEXT,
            project_id TEXT,
            user_id TEXT,
            graph_topology TEXT,
            color_preview TEXT,
            timestamp TIMESTAMP DEFAULT (datetime('now')),
            runtime_seconds REAL,
            active_runtime_seconds REAL,
            cwd TEXT,
            command TEXT,
            environment TEXT,
            version_date TEXT,
            name TEXT,
            success TEXT CHECK (success IN ('', 'Satisfactory', 'Failed')),
            custom_metrics TEXT NOT NULL DEFAULT '{}',
            thumb_label INTEGER CHECK (thumb_label IN (0, 1)),
            notes TEXT,
            log TEXT,
            trace_chat_history TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (parent_run_id) REFERENCES runs (run_id),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            UNIQUE (parent_run_id, name)
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS project_metric_kinds (
            project_id TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            metric_kind TEXT NOT NULL CHECK (metric_kind IN ('bool', 'int', 'float')),
            PRIMARY KEY (project_id, metric_key),
            FOREIGN KEY (project_id) REFERENCES projects (project_id)
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS project_tags (
            tag_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            color TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            UNIQUE (project_id, name)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS run_tags (
            run_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            PRIMARY KEY (run_id, tag_id),
            FOREIGN KEY (run_id) REFERENCES runs (run_id),
            FOREIGN KEY (tag_id) REFERENCES project_tags (tag_id)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_calls (
            run_id TEXT,
            node_uuid TEXT,
            input TEXT,
            input_hash TEXT,
            input_overwrite TEXT,
            output TEXT,
            color TEXT,
            label TEXT,
            api_type TEXT,
            stack_trace TEXT,
            timestamp TIMESTAMP DEFAULT (datetime('now')),
            PRIMARY KEY (run_id, node_uuid),
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            file_id TEXT PRIMARY KEY,
            content_hash TEXT,
            file_path TEXT
        )
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS attachments_content_hash_idx ON attachments(content_hash)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS original_input_lookup ON llm_calls(run_id, input_hash)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS runs_timestamp_idx ON runs(timestamp DESC)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS runs_project_idx ON runs(project_id, timestamp DESC)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS project_tags_project_idx ON project_tags(project_id, name)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS run_tags_run_idx ON run_tags(run_id)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS run_tags_tag_idx ON run_tags(tag_id)
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_project_locations (
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_location TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            UNIQUE (user_id, project_location)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS priors_applied (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prior_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            node_uuid TEXT,
            applied_at TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES runs (run_id),
            UNIQUE (prior_id, run_id, node_uuid)
        )
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS priors_applied_prior_idx ON priors_applied(prior_id)
    """
    )

    conn.commit()
