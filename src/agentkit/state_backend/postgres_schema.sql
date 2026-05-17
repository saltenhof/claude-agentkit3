
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE TABLE IF NOT EXISTS story_contexts (
            story_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            -- execution_route is nullable since AG3-021: non-implementing
            -- story types (concept/research) carry NULL instead of a
            -- sentinel value (see AG3-021 §2.1.1.1 StoryMode values).
            execution_route TEXT,
            implementation_contract TEXT,
            issue_nr INTEGER,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_id_idx
            ON story_contexts (story_id);

        CREATE TABLE IF NOT EXISTS projects (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            story_id_prefix TEXT NOT NULL UNIQUE,
            configuration JSONB NOT NULL,
            archived_at TIMESTAMPTZ NULL
        );

        CREATE INDEX IF NOT EXISTS projects_archived_at_idx
            ON projects (archived_at);

        CREATE TABLE IF NOT EXISTS story_number_counters (
            project_key TEXT PRIMARY KEY,
            next_story_number INTEGER NOT NULL,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE TABLE IF NOT EXISTS story_dependencies (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            depends_on_story_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (project_key, story_id, depends_on_story_id, kind),
            FOREIGN KEY (project_key) REFERENCES projects(key),
            FOREIGN KEY (project_key, story_id)
                REFERENCES story_contexts(project_key, story_id),
            FOREIGN KEY (project_key, depends_on_story_id)
                REFERENCES story_contexts(project_key, story_id)
        );

        CREATE INDEX IF NOT EXISTS story_dependencies_project_story_idx
            ON story_dependencies (project_key, story_id);

        CREATE INDEX IF NOT EXISTS story_dependencies_project_depends_idx
            ON story_dependencies (project_key, depends_on_story_id);

        CREATE TABLE IF NOT EXISTS parallelization_configs (
            project_key TEXT PRIMARY KEY,
            max_parallel_stories INTEGER NOT NULL,
            max_parallel_stories_per_repo INTEGER NULL,
            extra_config JSONB NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE TABLE IF NOT EXISTS story_are_links (
            story_id TEXT NOT NULL,
            are_item_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            PRIMARY KEY (story_id, are_item_id, kind),
            FOREIGN KEY (story_id) REFERENCES story_contexts(story_id)
        );

        CREATE TABLE IF NOT EXISTS project_api_tokens (
            token_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            label TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            last_used_at TIMESTAMPTZ NULL,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE INDEX IF NOT EXISTS project_api_tokens_project_idx
            ON project_api_tokens (project_key);

        CREATE TABLE IF NOT EXISTS phase_states (
            story_id TEXT PRIMARY KEY,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            paused_reason TEXT,
            review_round INTEGER NOT NULL,
            attempt_id TEXT,
            errors_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS phase_snapshots (
            story_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (story_id, phase)
        );

        CREATE TABLE IF NOT EXISTS attempts (
            run_id          VARCHAR        NOT NULL,
            phase           VARCHAR        NOT NULL,
            attempt         INTEGER        NOT NULL CHECK (attempt >= 1),
            outcome         VARCHAR        NOT NULL CHECK (outcome IN ('COMPLETED','FAILED','ESCALATED','SKIPPED','YIELDED','BLOCKED')),
            failure_cause   VARCHAR        NULL CHECK (
                failure_cause IS NULL OR failure_cause IN (
                    'GUARD_REJECTED','STRUCTURAL_CHECK_FAIL','SEMANTIC_REVIEW_FAIL','ADVERSARIAL_FINDING',
                    'POLICY_FAIL','WORKER_BLOCKED','INTEGRITY_FAIL','MERGE_FAIL','PREFLIGHT_FAIL',
                    'MAX_ROUNDS_EXCEEDED','TIMEOUT','GUARD_FAILED','HANDLER_EXCEPTION','PRECONDITION_FAILED',
                    'HANDLER_REPORTED_FAILED','HANDLER_REPORTED_ESCALATED'
                )
            ),
            started_at      TIMESTAMPTZ    NOT NULL,
            ended_at        TIMESTAMPTZ    NOT NULL CHECK (ended_at >= started_at),
            detail_json     JSONB          NULL,
            PRIMARY KEY (run_id, phase, attempt),
            CONSTRAINT failure_cause_consistency CHECK (
                (outcome IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NOT NULL)
                OR (outcome NOT IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_attempts_run_phase ON attempts (run_id, phase);
        CREATE INDEX IF NOT EXISTS idx_attempts_outcome ON attempts (outcome);

        CREATE TABLE IF NOT EXISTS flow_executions (
            story_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            level TEXT NOT NULL,
            owner TEXT NOT NULL,
            parent_flow_id TEXT,
            status TEXT NOT NULL,
            current_node_id TEXT,
            attempt_no INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS node_execution_ledgers (
            story_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            execution_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            last_outcome TEXT,
            last_attempt_no INTEGER,
            last_executed_at TEXT,
            PRIMARY KEY (story_id, flow_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS execution_events (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source_component TEXT NOT NULL,
            severity TEXT NOT NULL,
            phase TEXT,
            flow_id TEXT,
            node_id TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, event_id)
        );

        CREATE TABLE IF NOT EXISTS session_run_bindings (
            session_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            worktree_roots_json TEXT NOT NULL,
            binding_version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS story_execution_locks (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            lock_type TEXT NOT NULL,
            status TEXT NOT NULL,
            worktree_roots_json TEXT NOT NULL,
            binding_version TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deactivated_at TEXT,
            PRIMARY KEY (project_key, run_id, lock_type)
        );

        CREATE TABLE IF NOT EXISTS control_plane_operations (
            op_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT,
            session_id TEXT,
            operation_kind TEXT NOT NULL,
            phase TEXT,
            status TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS story_metrics (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            story_size TEXT NOT NULL,
            -- mode is nullable since AG3-021: non-implementing story
            -- types carry NULL execution_route.
            mode TEXT,
            processing_time_min DOUBLE PRECISION NOT NULL,
            qa_rounds INTEGER NOT NULL,
            increments INTEGER NOT NULL,
            final_status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            adversarial_findings INTEGER,
            adversarial_tests_created INTEGER,
            files_changed INTEGER,
            agentkit_version TEXT,
            agentkit_commit TEXT,
            config_version TEXT,
            llm_roles_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id)
        );

        CREATE TABLE IF NOT EXISTS override_records (
            override_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            target_node_id TEXT,
            override_type TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed_at TEXT
        );

        -- artifact_envelopes: typed Envelope-Persistenz via ArtifactManager (AG3-023 §2.1.4)
        -- artifact_records wurde in 3.4.0 entfernt (AG3-023 ReCut).
        CREATE TABLE IF NOT EXISTS artifact_envelopes (
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            schema_version VARCHAR NOT NULL,
            producer_type VARCHAR NOT NULL CHECK (producer_type IN ('WORKER', 'LLM_REVIEWER', 'DETERMINISTIC')),
            producer_id VARCHAR NOT NULL,
            producer_name VARCHAR NOT NULL,
            producer_version VARCHAR NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            status VARCHAR NOT NULL,
            artifact_class VARCHAR NOT NULL CHECK (artifact_class IN (
                'worker', 'qa', 'pipeline', 'telemetry', 'governance',
                'entwurf', 'handover', 'adversarial_test_sandbox'
            )),
            payload_json JSON,
            PRIMARY KEY (story_id, run_id, stage, attempt, artifact_class, producer_name)
        );

        CREATE INDEX IF NOT EXISTS artifact_envelopes_story_run_stage_attempt_idx
            ON artifact_envelopes (story_id, run_id, stage, attempt);

        CREATE TABLE IF NOT EXISTS qa_stage_results (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            stage_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            producer_component TEXT NOT NULL,
            status TEXT NOT NULL,
            blocking INTEGER NOT NULL,
            total_checks INTEGER NOT NULL,
            failed_checks INTEGER NOT NULL,
            warning_checks INTEGER NOT NULL,
            artifact_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, attempt_no, stage_id)
        );

        CREATE TABLE IF NOT EXISTS qa_findings (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            stage_id TEXT NOT NULL,
            finding_id TEXT NOT NULL,
            check_id TEXT NOT NULL,
            status TEXT NOT NULL,
            severity TEXT NOT NULL,
            blocking INTEGER NOT NULL,
            source_component TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            category TEXT,
            reason TEXT,
            description TEXT,
            detail TEXT,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, attempt_no, stage_id, finding_id)
        );

        CREATE TABLE IF NOT EXISTS decision_records (
            project_key TEXT,
            story_id TEXT NOT NULL,
            run_id TEXT,
            flow_id TEXT,
            decision_kind TEXT NOT NULL,
            attempt_nr INTEGER NOT NULL,
            status TEXT NOT NULL,
            passed INTEGER NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (story_id, decision_kind, attempt_nr)
        );

        CREATE TABLE IF NOT EXISTS stories (
            story_uuid UUID NOT NULL,
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_display_id TEXT NOT NULL,
            title TEXT NOT NULL,
            story_type TEXT NOT NULL,
            status TEXT NOT NULL,
            size TEXT NOT NULL,
            mode TEXT NULL,
            epic TEXT NOT NULL,
            module TEXT NOT NULL,
            participating_repos JSONB NOT NULL,
            change_impact TEXT NOT NULL,
            concept_quality TEXT NOT NULL,
            owner TEXT NOT NULL,
            risk TEXT NOT NULL,
            blocker TEXT NULL,
            labels JSONB NOT NULL,
            wave INTEGER NOT NULL,
            critical_path BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            PRIMARY KEY (story_uuid),
            UNIQUE (story_display_id),
            UNIQUE (project_key, story_number)
        );

        CREATE INDEX IF NOT EXISTS stories_project_key_idx
            ON stories (project_key);

        CREATE INDEX IF NOT EXISTS stories_project_key_number_idx
            ON stories (project_key, story_number);

        CREATE TABLE IF NOT EXISTS story_specifications (
            story_uuid UUID NOT NULL,
            need TEXT NULL,
            solution TEXT NULL,
            acceptance JSONB NOT NULL,
            definition_of_done JSONB NULL,
            concept_refs JSONB NULL,
            guardrail_refs JSONB NULL,
            external_sources JSONB NULL,
            PRIMARY KEY (story_uuid)
        );

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            op_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            result_payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            correlation_id TEXT NOT NULL,
            PRIMARY KEY (op_id)
        );
