
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

        -- AG3-050: story_dependencies (FK -> stories) is created AFTER the
        -- `stories` table below, because PostgreSQL requires the referenced
        -- table + its UNIQUE(story_display_id) constraint to exist at CREATE
        -- TABLE time. See the story_dependencies block following `stories`.

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
            story_id        VARCHAR        NOT NULL,
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
            PRIMARY KEY (story_id, run_id, phase, attempt),
            CONSTRAINT failure_cause_consistency CHECK (
                (outcome IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NOT NULL)
                OR (outcome NOT IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_attempts_story_run_phase ON attempts (story_id, run_id, phase);
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

        CREATE TABLE IF NOT EXISTS compaction_epochs (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            epoch INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id)
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
            -- binding_version carries a monotone positive-integer version token
            -- as canonical decimal TEXT (FK-17 §17.3a.16, minted DB-monotone by
            -- control_plane.runtime._next_binding_version). It stays TEXT so the
            -- same value flows verbatim into story_execution_locks (K5: not
            -- migrated to a numeric column here); the CHECK enforces the integer
            -- value domain (>= 1, no leading zeros / correlation tokens) at the
            -- persistence boundary. The named constraint mirrors the existing-
            -- schema ALTER (postgres_store._ensure_session_binding_constraints).
            binding_version TEXT NOT NULL
                CONSTRAINT session_run_bindings_binding_version_check
                CHECK (binding_version ~ '^[1-9][0-9]*$'),
            updated_at TEXT NOT NULL,
            -- AG3-137 (FK-56 §56.7a): session-binding status (active | revoked)
            -- plus a machine-readable revocation reason (vocabulary includes
            -- 'ownership_transferred'). Additive; DEFAULT 'active' keeps a
            -- pre-existing binding row lossless across the bootstrap.
            status TEXT NOT NULL DEFAULT 'active'
                CONSTRAINT session_run_bindings_status_check
                CHECK (status IN ('active', 'revoked')),
            revocation_reason TEXT
        );

        -- AG3-031 Pass-5 FK-22 §22.7 corrective: PK is (project_key, story_id, run_id, lock_type).
        -- Previous schema 3.6.0 had PK (project_key, run_id, lock_type) which omitted story_id,
        -- breaking 4-tuple isolation.  Corrected under the same SCHEMA_VERSION 3.6.0 as the
        -- old DB was never in production (migration migration step in postgres_store.py updated
        -- to match).
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
            PRIMARY KEY (project_key, story_id, run_id, lock_type)
        );

        -- AG3-031 Pass-2 FK-30-Korrektur 2026-05-24: schema corrected to
        -- (project_key, hook_event_name, matcher, command) per FK-30 §30.3.1.
        -- AG3-031 Hotfix 2026-05-25 (Governance-Loch): command added to PK/UNIQUE.
        -- FK-30 §30.3.1 registers multiple hooks under one matcher (e.g. "Bash"
        -- hosts branch_guard AND story_creation_guard); a 3-tuple key collapsed
        -- them and silently dropped guards.
        CREATE TABLE IF NOT EXISTS governance_hook_registrations (
            project_key      VARCHAR NOT NULL,
            hook_event_name  VARCHAR NOT NULL CHECK (hook_event_name IN ('PreToolUse','PostToolUse','PostToolUseFailure')),
            matcher          TEXT NOT NULL,
            command          TEXT NOT NULL,
            registered_at    TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, hook_event_name, matcher, command),
            UNIQUE (project_key, hook_event_name, matcher, command)
        );

        -- AG3-054 (FK-91, FK-22 §22.9): owner-scoped claim, instance-bound
        -- (AG3-139: ownership never ends by wall clock / TTL / lease -- FK-91
        -- §91.1a Regel 16; an orphaned claim ends ONLY via the AG3-138 startup
        -- reconciliation or an explicit admin_abort_inflight_operation).
        -- ``status`` stays the terminal-vs-claimed discriminator ('claimed' =
        -- in-flight reservation; 'committed'/'rejected'/'replayed'/'synced' =
        -- terminal). claimed_by holds the per-call owner token of an in-flight
        -- claim; claimed_at is a pure AUDIT instant (TEXT/ISO-8601, matching the
        -- table's other instants) consulted only by the ownership-scoped
        -- finalize/release CAS exact-match (WARNING-4, no psycopg datetime
        -- drift). Both are NULL on a terminal row (finalize clears claimed_by).
        -- AG3-140 (unified idempotency contract): this table IS the physical
        -- materialization of the formal ``inflight-operation-record``
        -- (identity_key: op_id; state-storage.entity). It is the SINGLE
        -- idempotency truth for EVERY mutating BC operation that follows the
        -- claim -> mutate -> finalize lifecycle (control-plane phases,
        -- story_context_manager mutations, task_management mutations) as well as
        -- the guard-counter's atomic single-transaction record. The legacy
        -- ``idempotency_keys`` table is retired (AG3-140): there is one record,
        -- one body-hash check, one in-flight fence.
        --   * ``story_id`` is NULLABLE (AG3-140): the formal
        --     inflight-operation-record is op_id-keyed and NOT story-scoped, and
        --     the concept explicitly contemplates a "waiting project-scoped
        --     claim" (state-storage.invariant, claim-acquisition ordering). A
        --     project-scoped operation (e.g. a task-management mutation) carries
        --     NO story_id. Relaxing NOT NULL is lossless on a pre-populated DB
        --     (every existing row keeps its non-null story_id).
        --   * ``request_body_hash`` is the SHA-256 of the canonical request body
        --     (op_id excluded), consulted on a claim-loser to decide replay
        --     (hash match) vs ``409 idempotency_mismatch`` (hash differs).
        --     Nullable/additive so a pre-populated DB survives the bootstrap
        --     losslessly (mirrors the AG3-137 additive-column style).
        CREATE TABLE IF NOT EXISTS control_plane_operations (
            op_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT,
            run_id TEXT,
            session_id TEXT,
            operation_kind TEXT NOT NULL,
            phase TEXT,
            status TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            claimed_by TEXT,
            claimed_at TEXT,
            -- AG3-137 (inflight-operation-record, FK-91 §91.1a rules 13/16):
            -- additive columns for the in-flight operation fence. Nullable so a
            -- DB pre-populated with legacy control_plane_operations rows
            -- survives the bootstrap losslessly; population + fencing arrive in
            -- AG3-138 / AG3-141.
            operation_epoch INTEGER,
            backend_instance_id TEXT,
            instance_incarnation INTEGER,
            declared_serialization_scope TEXT,
            finalized_at TEXT,
            -- AG3-140 (unified idempotency contract): body-hash of the request
            -- (op_id excluded) for the replay-vs-mismatch decision. Additive /
            -- nullable (lossless on a pre-populated DB).
            request_body_hash TEXT
        );

        CREATE INDEX IF NOT EXISTS control_plane_operations_run_idx
            ON control_plane_operations (project_key, story_id, run_id);

        -- AG3-137 Session-Ownership schema foundation (Postgres-only, K5).
        -- run_ownership_records is the canonical, DB-enforced ownership anchor
        -- of a story run (FK-17 §17.3.15, FK-56 §56.8a). Identity is one row per
        -- run; the partial-unique index below enforces the
        -- at_most_one_active_ownership_per_story invariant
        -- (formal.operating-modes.invariants) at the persistence layer, not as
        -- an application-side check. 'transferred' stays in the CHECK vocabulary
        -- (FK-17 §17.2c) but has NO writer in this strand -- the repository
        -- rejects persisting it fail-closed (AG3-137 scope §1).
        CREATE TABLE IF NOT EXISTS run_ownership_records (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            owner_session_id TEXT NOT NULL,
            ownership_epoch INTEGER NOT NULL CHECK (ownership_epoch >= 1),
            status TEXT NOT NULL CHECK (
                status IN (
                    'active', 'transferred', 'ended', 'reset', 'split', 'closed'
                )
            ),
            acquired_via TEXT NOT NULL CHECK (
                acquired_via IN ('setup', 'takeover', 'recovery')
            ),
            acquired_at TEXT NOT NULL,
            audit_ref TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, run_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS run_ownership_records_active_uidx
            ON run_ownership_records (project_key, story_id)
            WHERE status = 'active';

        -- AG3-143 (FK-44 §44.3a, SOLL-095): execution_contract_digests is the
        -- run-scoped, additive persistence of the execution_contract_digest
        -- formed at the committed setup-start. One row per run, inserted
        -- exactly once atomically with the run's minted run_ownership_records
        -- row (finalize_control_plane_start_phase_global_row); read-only after
        -- insert -- there is deliberately no UPDATE statement anywhere against
        -- this table (fail-closed: no silent digest drift for a running run).
        -- Postgres-only (K5), no SQLite mirror.
        CREATE TABLE IF NOT EXISTS execution_contract_digests (
            project_key                TEXT NOT NULL,
            story_id                   TEXT NOT NULL,
            run_id                     TEXT NOT NULL,
            execution_contract_digest  TEXT NOT NULL,
            digest_format_version      INTEGER NOT NULL,
            formed_at                  TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, run_id)
        );

        -- object_mutation_claims serialises mutations per mutated object
        -- (state-storage.entity.object-mutation-claim; FK-91 §91.1a rules 13/16).
        -- Instance-bound (backend_instance_id + instance_incarnation) and never
        -- expiring by wall clock: there is deliberately NO ttl/expiry column
        -- (object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock).
        CREATE TABLE IF NOT EXISTS object_mutation_claims (
            project_key TEXT NOT NULL,
            serialization_scope TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            op_id TEXT NOT NULL,
            backend_instance_id TEXT NOT NULL,
            instance_incarnation INTEGER NOT NULL CHECK (instance_incarnation >= 1),
            acquired_at TEXT NOT NULL,
            queue_position INTEGER NOT NULL CHECK (queue_position >= 0),
            PRIMARY KEY (project_key, serialization_scope, scope_key)
        );

        -- takeover_transfer_records: ONE row per participating repo
        -- (state-storage.entity.takeover-transfer-record, state-storage v5). The
        -- transfer record REPLACES the former takeover-worktree-snapshot
        -- (SOLL-147): the handover object is a SHA, never a file snapshot. Only
        -- the identity is NOT NULL; the attributes are materialised across the
        -- transfer lifecycle by the productive writer AG3-148.
        CREATE TABLE IF NOT EXISTS takeover_transfer_records (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            ownership_epoch INTEGER NOT NULL CHECK (ownership_epoch >= 1),
            repo_id TEXT NOT NULL,
            takeover_base_sha TEXT,
            last_push_at TEXT,
            push_lag_hint TEXT,
            base_quality TEXT,
            challenge_ref TEXT,
            confirm_ref TEXT,
            PRIMARY KEY (project_key, story_id, run_id, ownership_epoch, repo_id)
        );

        -- backend_instance_identity: persistent store for backend_instance_id +
        -- a monotone boot incarnation counter (IMPL-004 persistence part; FK-91
        -- §91.1a rule 16). AG3-138 creates/increments on boot.
        CREATE TABLE IF NOT EXISTS backend_instance_identity (
            backend_instance_id TEXT PRIMARY KEY,
            instance_incarnation INTEGER NOT NULL CHECK (instance_incarnation >= 1),
            updated_at TEXT NOT NULL
        );

        -- edge_command_records: the Edge-Command-Queue persistence (Auftrag/
        -- Meldung, FK-91 §91.1b, AG3-145). Replaces backend-side physical
        -- worktree operations (FK-10 §10.2.4a): the backend commissions a
        -- command here, the Project Edge fetches/acks it (GET, delivered_at),
        -- executes it dev-locally and reports a result (POST .../result). Brand
        -- new / forward-only table (mirrors the AG3-143 execution_contract_digests
        -- precedent -- no additive ALTER/backfill needed). No TTL/expiry column
        -- by design (SOLL-165, FK-91 §91.1a Rule 16): an open command never ends
        -- by wall clock -- it stays visibly open until a result terminates it.
        CREATE TABLE IF NOT EXISTS edge_command_records (
            command_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            command_kind TEXT NOT NULL CHECK (
                command_kind IN (
                    'provision_worktree', 'teardown_worktree', 'preflight_probe',
                    'sync_push', 'takeover_reconcile', 'merge_local'
                )
            ),
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('created', 'delivered', 'completed', 'failed')
            ),
            ownership_epoch INTEGER NOT NULL CHECK (ownership_epoch >= 1),
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            completed_at TEXT,
            result_op_id TEXT,
            result_type TEXT,
            result_payload_json TEXT
        );

        CREATE INDEX IF NOT EXISTS edge_command_records_session_open_idx
            ON edge_command_records (run_id, session_id, status);

        CREATE TABLE IF NOT EXISTS story_metrics (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            story_size TEXT NOT NULL,
            -- mode is the standard/fast axis (WireStoryMode), FK-24 §24.3.298:
            -- closure metrics are tagged with standard/fast so fast runs are
            -- separately aggregable. This is NOT execution_route (AG3-052).
            -- Column stays nullable for legacy rows; new rows always carry a
            -- value (StoryContext.mode defaults to 'standard').
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
            consumed_at TEXT,
            -- AG3-108: override->check correlation (FK-69 §69.11 rule 3, §69.15.6
            -- rule 5). NULL for non-check overrides; set when this override
            -- suppresses a specific QA check (outcome = overridden).
            check_id TEXT
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
            -- AG3-015: 'prompt_audit' added (FK-44 §44.6). Idempotent
            -- side-by-side migration via SCHEMA_VERSION bump 3.6.0->3.7.0.
            artifact_class VARCHAR NOT NULL CHECK (artifact_class IN (
                'worker', 'qa', 'pipeline', 'telemetry', 'governance',
                'entwurf', 'handover', 'adversarial_test_sandbox',
                'prompt_audit'
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

        -- AG3-108 (FK-69 §69.15): qa_check_outcomes. Schema-Owner verify-system,
        -- DB-Owner telemetry-and-events via ProjectionAccessor / FacadeQACheckOutcomesRepository.
        -- Records EVERY executed QA check: triggered (finding produced), clean (PASS),
        -- or overridden (suppressed). Composite PK enforces uniqueness per
        -- (project, run, stage, attempt, check).
        CREATE TABLE IF NOT EXISTS qa_check_outcomes (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            check_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            check_proposal_ref TEXT,
            override_id TEXT,
            PRIMARY KEY (project_key, run_id, stage_id, attempt_no, check_id)
        );

        -- AG3-037 (FK-68 §68.8): governance risk window. Schema-Owner +
        -- DB-Owner telemetry-and-events via
        -- ProjectionAccessor.record_risk_window_event. Append-only rolling
        -- window of NormalizedEvents; event_id unique within a run.
        CREATE TABLE IF NOT EXISTS risk_window (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            risk_category TEXT NOT NULL,
            severity TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            source_event_type TEXT NOT NULL,
            payload_excerpt_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (project_key, run_id, event_id)
        );

        -- AG3-028 (FK-41 §41.3.1, FK-69): fc_incidents. Schema-Owner
        -- failure-corpus, DB-Owner telemetry-and-events via ProjectionAccessor.
        -- Append-only (genau ein Datensatz pro incident_id). Schreibpfad
        -- ausschliesslich ueber Telemetry.write_projection(FC_INCIDENTS, record).
        -- Schema exakt nach FK-41 §41.3.1 (Codex-r1 Remediation 2026-06-01):
        -- project_key NOT NULL, incident_id PK im Format FC-YYYY-NNNN, run_id
        -- NOT NULL, role CHECK (worker|qa|governance), phase/model/symptom
        -- NOT NULL, evidence_json = Liste von Strings.
        CREATE TABLE IF NOT EXISTS fc_incidents (
            project_key TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            story_id TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN (
                'scope_drift', 'architecture_violation', 'evidence_fabrication',
                'hallucination', 'test_omission', 'assertion_weakness',
                'unsafe_refactor', 'policy_violation', 'tool_misuse',
                'state_desync', 'requirements_miss', 'review_evasion'
            )),
            severity TEXT NOT NULL CHECK (severity IN (
                'low', 'medium', 'high', 'critical'
            )),
            phase TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN (
                'worker', 'qa', 'governance'
            )),
            model TEXT NOT NULL,
            symptom TEXT NOT NULL,
            evidence_json JSON NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            incident_status TEXT NOT NULL DEFAULT 'observed' CHECK (incident_status IN (
                'observed', 'promoted', 'closed_one_off', 'archived'
            )),
            tags JSON,
            impact TEXT,
            pattern_ref TEXT,
            -- Codex-r2 (User-Entscheidung 2026-06-01): incident_id ist GLOBAL
            -- eindeutig (kein Projekt-Segment, keine per-project-Nummerierung).
            -- PK = incident_id allein; project_key bleibt NOT-NULL-Spalte und
            -- read/purge filtern weiterhin zwingend nach project_key (r1-Fix).
            -- Die FC-YYYY-NNNN-Nummern stammen aus einem globalen Per-Jahr-
            -- Zaehler (fc_incident_counters, gekeyt auf year allein).
            PRIMARY KEY (incident_id),
            -- incident_id muss exakt FC-YYYY-NNNN sein (NNNN >= 4 Stellen,
            -- spiegelt den Pydantic-Validator ^FC-\d{4}-\d{4,}$; FAIL-CLOSED).
            CONSTRAINT fc_incidents_id_format
                CHECK (incident_id ~ '^FC-[0-9]{4}-[0-9]{4,}$'),
            -- evidence_json muss ein JSON-Array AUS STRINGS sein (FK-41 §41.4.1
            -- evidence=list[str]). Der jsonpath-Filter trifft jedes Element, das
            -- KEIN String ist; existiert ein solches, schlaegt der CHECK fehl.
            CONSTRAINT fc_incidents_evidence_is_string_array
                CHECK (jsonb_typeof(evidence_json::jsonb) = 'array'
                       AND NOT (evidence_json::jsonb @? '$[*] ? (@.type() != "string")')),
            -- tags ist optional; wenn gesetzt ebenfalls ein JSON-Array AUS
            -- STRINGS (FK-41 §41.4.1). NULL erlaubt.
            CONSTRAINT fc_incidents_tags_is_string_array
                CHECK (tags IS NULL
                       OR (jsonb_typeof(tags::jsonb) = 'array'
                           AND NOT (tags::jsonb @? '$[*] ? (@.type() != "string")')))
        );

        CREATE INDEX IF NOT EXISTS idx_fc_incidents_project_story_run
            ON fc_incidents (project_key, story_id, run_id);

        CREATE INDEX IF NOT EXISTS idx_fc_incidents_incident_status
            ON fc_incidents (incident_status);

        -- AG3-028 (Codex-r2): GLOBALER Per-Jahr-Zaehler fuer die global
        -- eindeutige FC-YYYY-NNNN-Allokation (PK = year allein, KEIN
        -- project_key). Race-sicher in EINEM atomaren Statement:
        -- INSERT ... ON CONFLICT(year) DO UPDATE SET next_seq = next_seq + 1
        -- RETURNING next_seq - 1 (deckt Initial-Row + Folge-Allokation ab;
        -- kein SELECT-dann-INSERT-TOCTOU).
        CREATE TABLE IF NOT EXISTS fc_incident_counters (
            year INTEGER NOT NULL,
            next_seq INTEGER NOT NULL,
            PRIMARY KEY (year)
        );

        -- AG3-040 Sub-Block (b) (FK-41 §41.3.2, FK-69 §69.3): fc_patterns.
        -- Schema-Owner failure-corpus, DB-Owner telemetry-and-events. Schema
        -- exakt nach FK-41 §41.3.2 (Pflicht-/Optional-Attribute). status =
        -- pattern-status (4 Werte: candidate|accepted|rejected|retired),
        -- category = FailureCategory (12 Werte), promotion_rule/risk_level mit
        -- den FK-41-Enums. incident_refs = JSON-Array von incident_id-Strings
        -- (FK-41: "JSON-Array der zugehoerigen incident_id-Werte"). Diese Story
        -- liefert NUR Tabelle + Repository-Skelett; der Writer (PatternPromotion)
        -- folgt in einer Folge-Story (FK-41 §41.5, Out of Scope).
        CREATE TABLE IF NOT EXISTS fc_patterns (
            pattern_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'candidate', 'accepted', 'rejected', 'retired'
            )),
            category TEXT NOT NULL CHECK (category IN (
                'scope_drift', 'architecture_violation', 'evidence_fabrication',
                'hallucination', 'test_omission', 'assertion_weakness',
                'unsafe_refactor', 'policy_violation', 'tool_misuse',
                'state_desync', 'requirements_miss', 'review_evasion'
            )),
            invariant TEXT NOT NULL,
            incident_refs JSON NOT NULL,
            promotion_rule TEXT NOT NULL CHECK (promotion_rule IN (
                'repetition', 'high_severity', 'favorable_checkability'
            )),
            risk_level TEXT NOT NULL CHECK (risk_level IN (
                'medium', 'high', 'critical'
            )),
            incident_count INTEGER NOT NULL,
            confirmed_at TIMESTAMPTZ,
            confirmed_by TEXT CHECK (confirmed_by IS NULL OR confirmed_by = 'human'),
            owner TEXT,
            -- check_ref ist FK auf fc_check_proposals(check_id) (FK-41 §41.3.2:234).
            -- Die FK-Constraint selbst wird idempotent NACH dem Anlegen beider
            -- Tabellen ergaenzt (zirkulaere FK mit fc_check_proposals.pattern_ref;
            -- siehe postgres_store._ensure_failure_corpus_constraints). Beide Refs
            -- sind nullable.
            check_ref TEXT,
            retired_at TIMESTAMPTZ,
            PRIMARY KEY (pattern_id),
            -- pattern_id == FP-NNNN (NNNN >= 4 Stellen, NUR Ziffern; spiegelt den
            -- FK-41-§41.3.2-Vertrag und den Pydantic-Validator, FAIL-CLOSED).
            CONSTRAINT fc_patterns_id_format
                CHECK (pattern_id ~ '^FP-[0-9]{4,}$'),
            -- incident_refs ist ein JSON-Array AUS STRINGS (FK-41 §41.3.2). Der
            -- jsonpath-Filter trifft jedes Nicht-String-Element; existiert eines,
            -- schlaegt der CHECK fehl (symmetrisch zum fc_incidents-evidence-CHECK).
            CONSTRAINT fc_patterns_incident_refs_is_string_array
                CHECK (jsonb_typeof(incident_refs::jsonb) = 'array'
                       AND NOT (incident_refs::jsonb @? '$[*] ? (@.type() != "string")')),
            -- FK-41 §41.3.2:239: kein Pattern wechselt in 'accepted' ohne
            -- confirmed_by = 'human'. Konditionaler CHECK (FAIL-CLOSED,
            -- Lifecycle-Invariante, spiegelt den Pydantic-model_validator).
            CONSTRAINT fc_patterns_accepted_human
                CHECK (status <> 'accepted'
                       OR confirmed_by IS NOT DISTINCT FROM 'human')
        );

        CREATE INDEX IF NOT EXISTS idx_fc_patterns_project
            ON fc_patterns (project_key);

        CREATE INDEX IF NOT EXISTS idx_fc_patterns_status
            ON fc_patterns (status);

        -- AG3-040 Sub-Block (b) (FK-41 §41.3.3, FK-69 §69.3): fc_check_proposals.
        -- Schema-Owner failure-corpus, DB-Owner telemetry-and-events. Schema
        -- exakt nach FK-41 §41.3.3. status = check-status (5 Werte: draft|approved|
        -- active|rejected|retired), check_type = 6 FK-41-Werte, false_positive_risk
        -- = niedrig|mittel|hoch. pattern_ref ist FK auf fc_patterns(pattern_id)
        -- (FK-41 §41.3.3: "Verweis auf fc_patterns.pattern_id"). positive_/
        -- negative_fixtures = JSON-Arrays. Diese Story liefert NUR Tabelle +
        -- Repository-Skelett; der Writer (CheckFactory) folgt in einer Folge-Story
        -- (FK-41 §41.6, Out of Scope).
        CREATE TABLE IF NOT EXISTS fc_check_proposals (
            check_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'draft', 'approved', 'active', 'rejected', 'retired'
            )),
            pattern_ref TEXT NOT NULL REFERENCES fc_patterns(pattern_id),
            invariant TEXT NOT NULL,
            check_type TEXT NOT NULL CHECK (check_type IN (
                'Changed-File-Policy', 'Artifact-Completeness', 'Test-Obligation',
                'Sensitive-Path-Guard', 'Forbidden-Dependency', 'Fixture-Replay'
            )),
            pipeline_stage TEXT NOT NULL,
            pipeline_layer INTEGER NOT NULL,
            owner TEXT NOT NULL,
            false_positive_risk TEXT NOT NULL CHECK (false_positive_risk IN (
                'low', 'medium', 'high'
            )),
            positive_fixtures JSON NOT NULL,
            negative_fixtures JSON NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            approved_at TIMESTAMPTZ,
            approved_by TEXT CHECK (approved_by IS NULL OR approved_by = 'human'),
            rejected_reason TEXT,
            effectiveness_last_checked_at TIMESTAMPTZ,
            true_positives_90d INTEGER,
            false_positives_90d INTEGER,
            no_findings_90d INTEGER,
            PRIMARY KEY (check_id),
            -- check_id == CHK-NNNN (NNNN >= 4 Stellen, NUR Ziffern; FK-41
            -- §41.3.3, FAIL-CLOSED).
            CONSTRAINT fc_check_proposals_id_format
                CHECK (check_id ~ '^CHK-[0-9]{4,}$'),
            -- positive_/negative_fixtures sind JSON-Arrays von {description,
            -- expected}-Objekten (FK-41 §41.3.3:265-266). Der jsonpath-Filter
            -- trifft jedes Element, das KEIN Objekt mit BEIDEN Pflicht-Keys ist;
            -- existiert ein solches, schlaegt der CHECK fehl. Damit kann die DB
            -- keinen fixtures-Wert halten, den der Repo-Decoder ablehnt
            -- (FAIL-CLOSED, kein DB-state-the-repo-rejects-Loch).
            CONSTRAINT fc_check_proposals_positive_fixtures_shape
                CHECK (jsonb_typeof(positive_fixtures::jsonb) = 'array'
                       AND NOT (positive_fixtures::jsonb @? '$[*] ? (@.type() != "object"
                                || !exists(@.description) || !exists(@.expected))')),
            CONSTRAINT fc_check_proposals_negative_fixtures_shape
                CHECK (jsonb_typeof(negative_fixtures::jsonb) = 'array'
                       AND NOT (negative_fixtures::jsonb @? '$[*] ? (@.type() != "object"
                                || !exists(@.description) || !exists(@.expected))')),
            -- FK-41 §41.3.3:282: approved_by muss 'human' sein; 'active' ist ein
            -- Vorwaerts-Uebergang aus 'approved' (FK-41 §41.6.7) und erbt die
            -- Pflicht. Konditionaler CHECK (FAIL-CLOSED, Lifecycle-Invariante,
            -- spiegelt den Pydantic-model_validator).
            CONSTRAINT fc_check_proposals_approved_human
                CHECK (status NOT IN ('approved', 'active')
                       OR approved_by IS NOT DISTINCT FROM 'human')
        );

        CREATE INDEX IF NOT EXISTS idx_fc_check_proposals_project
            ON fc_check_proposals (project_key);

        CREATE INDEX IF NOT EXISTS idx_fc_check_proposals_pattern_ref
            ON fc_check_proposals (pattern_ref);

        CREATE INDEX IF NOT EXISTS idx_fc_check_proposals_status
            ON fc_check_proposals (status);

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
            -- AG3-057: Trigger 3 input — new code/module structures introduced.
            -- Default FALSE = fail-closed: absence does not trigger Exploration.
            new_structures BOOLEAN NOT NULL DEFAULT FALSE,
            -- AG3-068: VectorDB-conflict producer flag (FK-21 §21.12).
            -- Default FALSE = fail-closed: only a resolved stage-2 conflict sets it.
            vectordb_conflict_resolved BOOLEAN NOT NULL DEFAULT FALSE,
            -- AG3-072 (FK-54 §54.8.5): materialized split lineage. ``split_from``
            -- is the cancelled source on a successor; ``split_successors`` is the
            -- real successor id list on the source. Defaults NULL / '[]'.
            split_from TEXT NULL,
            split_successors JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            PRIMARY KEY (story_uuid),
            UNIQUE (story_display_id),
            -- AG3-050 A3: project-scoped UNIQUE so story_dependencies can use a
            -- COMPOSITE FK (project_key, story_id)->(project_key,
            -- story_display_id) and reject cross-project edges fail-closed.
            UNIQUE (project_key, story_display_id),
            UNIQUE (project_key, story_number)
        );

        CREATE INDEX IF NOT EXISTS stories_project_key_idx
            ON stories (project_key);

        CREATE INDEX IF NOT EXISTS stories_project_key_number_idx
            ON stories (project_key, story_number);

        -- AG3-096 (FK-77): task-management canonical state. Tasks are not
        -- pipeline-managed; this schema stores only task state and typed links.
        CREATE TABLE IF NOT EXISTS tm_tasks (
            project_key TEXT NOT NULL,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('reminder', 'actionable')),
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high')),
            status TEXT NOT NULL CHECK (status IN ('open', 'done', 'dismissed')),
            origin TEXT NOT NULL CHECK (origin IN (
                'closure', 'verify', 'governance', 'human'
            )),
            source_story_id TEXT,
            execution_report_ref TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ,
            resolved_by TEXT CHECK (resolved_by IS NULL OR resolved_by IN ('human', 'agent')),
            PRIMARY KEY (project_key, task_id),
            CONSTRAINT tm_tasks_id_format
                CHECK (task_id ~ '^TM-[0-9]{4}-[0-9]{4,}$'),
            CONSTRAINT tm_tasks_resolution_consistency
                CHECK (
                    (status = 'open' AND resolved_at IS NULL AND resolved_by IS NULL)
                    OR (
                        status IN ('done', 'dismissed')
                        AND resolved_at IS NOT NULL
                        AND resolved_by IS NOT NULL
                    )
                )
        );

        CREATE TABLE IF NOT EXISTS tm_task_links (
            project_key TEXT NOT NULL,
            task_id TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('task', 'story')),
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN (
                'relates_to', 'spawned_story', 'duplicate_of'
            )),
            PRIMARY KEY (project_key, task_id, target_kind, target_id, kind),
            FOREIGN KEY (project_key, task_id)
                REFERENCES tm_tasks(project_key, task_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS tm_task_links_target_idx
            ON tm_task_links (project_key, target_kind, target_id);

        -- AG3-050 (FK-02 §2.11.3, FK-18 §18.6a/§18.13): the StoryDependency edge
        -- binds to the STATIC story stammdaten (`stories`), NOT the runtime
        -- projection (`story_contexts`). story_id/depends_on_story_id hold
        -- display-ID strings, so the FK target columns are display-ID columns.
        -- A3: the FK is COMPOSITE on (project_key, story_id) ->
        -- stories(project_key, story_display_id) for BOTH endpoints, so an edge
        -- whose endpoints live in a different project is rejected fail-closed at
        -- the FK (not merely "display-ID exists somewhere"). story_display_id is
        -- chosen over story_uuid because the columns carry display-ID strings
        -- (no wire/data change), and over story_number because that would force
        -- storing numbers instead of the display ID.
        -- Placed after `stories` so the referenced UNIQUE columns already exist.
        CREATE TABLE IF NOT EXISTS story_dependencies (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            depends_on_story_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (project_key, story_id, depends_on_story_id, kind),
            FOREIGN KEY (project_key) REFERENCES projects(key),
            FOREIGN KEY (project_key, story_id)
                REFERENCES stories(project_key, story_display_id),
            FOREIGN KEY (project_key, depends_on_story_id)
                REFERENCES stories(project_key, story_display_id)
        );

        CREATE INDEX IF NOT EXISTS story_dependencies_project_story_idx
            ON story_dependencies (project_key, story_id);

        CREATE INDEX IF NOT EXISTS story_dependencies_project_depends_idx
            ON story_dependencies (project_key, depends_on_story_id);

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

        -- AG3-140: the legacy ``idempotency_keys`` table is retired. The unified
        -- ``control_plane_operations`` inflight-operation-record above is now the
        -- SINGLE idempotency truth (one record, one body-hash check, one in-flight
        -- fence). No new DDL here; a pre-populated DB may still physically carry an
        -- orphan ``idempotency_keys`` table (harmless — nothing reads or writes it).

        -- AG3-048 (FK-43 §43.4.1, bc-cut-decisions.md §BC 11): skill_bindings.
        -- Schema-Owner agent-skills (SkillBinding entity, AG3-027); DB-Owner
        -- state_backend. Kanonische Wahrheit (concept/domain-design
        -- /05-telemetrie-und-metriken.md §5: Postgres). Spalten spiegeln EXAKT
        -- das SkillBinding-Modell (kein manifest_digest — das Modell ist Owner
        -- der Shape). Upsert auf (project_key, skill_name). status deckt ALLE
        -- SECHS SkillLifecycleStatus-Werte ab (FAIL-CLOSED CHECK). Identisches
        -- Parallel-Schema in sqlite_store.py fuer Unit-Tests.
        CREATE TABLE IF NOT EXISTS skill_bindings (
            binding_id      VARCHAR NOT NULL,
            project_key     VARCHAR NOT NULL,
            skill_name      VARCHAR NOT NULL,
            bundle_id       VARCHAR NOT NULL,
            bundle_version  VARCHAR NOT NULL,
            target_path     TEXT NOT NULL,
            binding_mode    VARCHAR NOT NULL CHECK (binding_mode IN ('SYMLINK', 'JUNCTION')),
            status          VARCHAR NOT NULL CHECK (status IN (
                'REQUESTED', 'PROFILE_RESOLVED', 'BUNDLE_SELECTED',
                'BOUND', 'VERIFIED', 'REJECTED'
            )),
            pinned_at       TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (binding_id),
            UNIQUE (project_key, skill_name)
        );

        CREATE INDEX IF NOT EXISTS idx_skill_bindings_project_skill
            ON skill_bindings (project_key, skill_name);

        -- AG3-032 (FK-55 §55.8 / §55.10.5, FK-31 §31.2.7): governance_freeze_records.
        -- Kanonische (Wahrheits-)Seite der dualen Conflict-Freeze-Materialisierung;
        -- die lokale .agentkit/governance/freeze.json ist der hook-schnelle Export
        -- mit identischem freeze_version. Schema-/DB-Owner governance-and-guards.
        -- Genau ein aktiver Freeze pro Story (PK story_id). Identisches Parallel-
        -- Schema in sqlite_store.py fuer Unit-Tests.
        CREATE TABLE IF NOT EXISTS governance_freeze_records (
            story_id        TEXT NOT NULL,
            frozen_at       TEXT NOT NULL,
            freeze_reason   TEXT NOT NULL,
            freeze_version  INTEGER NOT NULL,
            PRIMARY KEY (story_id)
        );

        CREATE TABLE IF NOT EXISTS guard_decisions (
            project_key       TEXT NOT NULL,
            story_id          TEXT NOT NULL,
            run_id            TEXT NOT NULL,
            flow_id           TEXT NOT NULL,
            guard_decision_id TEXT NOT NULL,
            guard_key         TEXT NOT NULL,
            outcome           TEXT NOT NULL CHECK (outcome IN (
                'PASS', 'WARNING', 'ERROR'
            )),
            decided_at        TIMESTAMPTZ NOT NULL,
            node_id           TEXT,
            reason            TEXT,
            evidence_ref      TEXT,
            PRIMARY KEY (project_key, run_id, guard_decision_id)
        );

        CREATE INDEX IF NOT EXISTS idx_guard_decisions_story_run
            ON guard_decisions (project_key, story_id, run_id);

        CREATE TABLE IF NOT EXISTS conflict_freeze_proofs (
            project_key             TEXT NOT NULL,
            story_id                TEXT NOT NULL,
            run_id                  TEXT NOT NULL,
            proof_id                TEXT NOT NULL,
            activated_at            TIMESTAMPTZ NOT NULL,
            blocked_principal       TEXT NOT NULL,
            resolution_service_path TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, run_id, proof_id)
        );

        CREATE INDEX IF NOT EXISTS idx_conflict_freeze_proofs_story_run
            ON conflict_freeze_proofs (project_key, story_id, run_id);

        CREATE TABLE IF NOT EXISTS story_custom_field_definitions (
            project_key                 TEXT NOT NULL,
            field_key                   TEXT NOT NULL,
            display_name                TEXT NOT NULL,
            field_type                  TEXT NOT NULL CHECK (field_type IN (
                'text', 'number', 'boolean', 'enum', 'date', 'json'
            )),
            provider                    TEXT NOT NULL,
            provider_field_ref          TEXT NOT NULL,
            is_required                 BOOLEAN NOT NULL,
            is_writable_by_agentkit     BOOLEAN NOT NULL,
            allowed_values              JSONB NOT NULL,
            PRIMARY KEY (project_key, field_key)
        );

        CREATE TABLE IF NOT EXISTS story_custom_field_values (
            project_key             TEXT NOT NULL,
            story_id                TEXT NOT NULL,
            field_key               TEXT NOT NULL,
            value                   TEXT NOT NULL,
            value_status            TEXT NOT NULL CHECK (value_status IN (
                'present', 'missing', 'invalid', 'conflict'
            )),
            source                  TEXT NOT NULL CHECK (source IN (
                'provider', 'agentkit', 'human'
            )),
            last_synced_at          TIMESTAMPTZ,
            last_written_by         TEXT,
            provider_sync_status    TEXT NOT NULL CHECK (provider_sync_status IN (
                'in_sync', 'pending', 'failed', 'not_writable'
            )),
            conflict_detected       BOOLEAN NOT NULL,
            last_sync_attempt_at    TIMESTAMPTZ,
            PRIMARY KEY (project_key, story_id, field_key),
            FOREIGN KEY (project_key, field_key)
                REFERENCES story_custom_field_definitions(project_key, field_key)
        );

        -- AG3-034 (FK-24 §24.3.3, FK-22 §22.3.1 Check 10): project_mode_lock.
        -- Projektweiter Control-Plane Mode-Lock fuer die Fast/Standard-Mutual-
        -- Exclusion. AG3-034 stellt NUR den Read-Pfad fuer Preflight-Check 10
        -- (no_competing_story_mode_active) her; die atomare Setzung beim
        -- Story-Start ist AG3-018-Folge (story.md §2.1.2 / §2.2). active_mode ist
        -- NULL (idle) oder einer der WireStoryMode-Werte; holder_count >= 0.
        -- active_mode liegt auf der ENTKOPPELTEN fast/standard-mode-Achse
        -- (WireStoryMode, FK-24 §24.3.3), NICHT auf der execution_route-Achse
        -- (execution/exploration war Achsen-Drift, hier korrigiert).
        -- Schema-/DB-Owner governance-and-guards. Identisches Parallel-Schema in
        -- sqlite_store.py fuer Unit-Tests.
        CREATE TABLE IF NOT EXISTS project_mode_lock (
            project_key    TEXT NOT NULL,
            active_mode    TEXT CHECK (active_mode IS NULL OR active_mode IN (
                'standard', 'fast'
            )),
            holder_count   INTEGER NOT NULL DEFAULT 0 CHECK (holder_count >= 0),
            updated_at     TEXT NOT NULL,
            PRIMARY KEY (project_key)
        );

        -- AG3-039 (FK-50 §50.3 CP 7, formal.installer.entities
        -- §project-registration): project_registry. Canonical State-Backend
        -- registration written by Installer-Checkpoint 7. Schema-/DB-Owner
        -- installation-and-bootstrap. IDENTISCHES Parallel-Schema in
        -- sqlite_store.py (Postgres ist kanonisch). project_root is UNIQUE so a
        -- single filesystem root maps to exactly one registration; runtime_profile
        -- is constrained to the RuntimeProfile wire values (core | are).
        -- last_verified_at / last_upgraded_at are NULL until verify-project /
        -- an upgrade rerun touch them. The lifecycle timestamps are TIMESTAMPTZ
        -- (story §2.1.1), matching the other Postgres temporal columns that carry
        -- a real instant (e.g. prompt_bundle_pins.pinned_at, runs.started_at). The
        -- SQLite parallel path keeps ISO-8601 TEXT (SQLite has no native
        -- timestamptz affinity); the mapper roundtrips datetime against both.
        CREATE TABLE IF NOT EXISTS project_registry (
            project_key      TEXT NOT NULL,
            project_root     TEXT NOT NULL,
            github_owner     TEXT NOT NULL,
            github_repo      TEXT NOT NULL,
            runtime_profile  TEXT NOT NULL CHECK (runtime_profile IN (
                'core', 'are'
            )),
            config_version   TEXT NOT NULL,
            config_digest    TEXT NOT NULL,
            registered_at    TIMESTAMPTZ NOT NULL,
            last_verified_at TIMESTAMPTZ,
            last_upgraded_at TIMESTAMPTZ,
            PRIMARY KEY (project_key),
            UNIQUE (project_root)
        );

        -- AG3-038 (FK-62 §62.2.1-62.2.7, FK-60 §60.3.4): analytics fact tables
        -- + sync_state + guard_invocation_counters scratchpad. Schema-/DB-Owner
        -- kpi-and-dashboard; canonical Postgres + SQLite test-parallel schema
        -- with IDENTICAL semantics (sqlite_store._ensure_analytics_tables).
        --
        -- SCHEMA PLACEMENT DECISION (deviation from story §8 "analytics. prefix"):
        -- FK-60 §60.3 sketches a logical ``analytics`` schema next to ``runtime``.
        -- AK3's persistence reality (FK-18 §18.9a, AG3-005/AG3-053) is ONE versioned
        -- schema per SCHEMA_VERSION (``ak3_v<slug>``), selected via search_path; ALL
        -- ~18 existing tables live flat in it and NO separate ``analytics``/``runtime``
        -- schema exists anywhere. A top-level ``CREATE SCHEMA analytics`` would be a
        -- single, cross-version-SHARED namespace, breaking the side-by-side
        -- versioning invariant (each version must own an isolated table set). So the
        -- fact tables join the SAME versioned schema as every other table, exactly
        -- as story §2.1.4 already mandates for SQLite (no schema prefix there). The
        -- ``analytics.`` prefix in story §2.1.1 is treated as a logical-grouping note,
        -- not a literal second Postgres schema. Columns/PKs follow story §2.1.1
        -- (the binding spec's curated KPI subset) verbatim. TIMESTAMPTZ for instants
        -- matches the project_registry/runs temporal convention; SQLite uses ISO-8601
        -- TEXT (no native timestamptz affinity), the mapper roundtrips datetime.
        --
        -- Mandantenregel (FK-62 §62.2): project_key is the leading scope key.
        -- AG3-117: FK-62 §62.2 reconciled fact-table column sets (renames, new
        -- columns, drops, are_gate_passed bool). Postgres-canonical dialect
        -- (TIMESTAMPTZ/BIGINT/BOOLEAN/DOUBLE PRECISION) mirrors the SQLite
        -- migration v_3_6_fact_reconciliation.sql column set + nullability.
        --
        -- AG3-117 EXISTING-DB RECONCILIATION: these ``CREATE TABLE IF NOT EXISTS``
        -- statements build the FK-62 fact tables on a FRESH database. A Postgres DB
        -- that still carries the OLD (pre-AG3-117 / AG3-038) fact tables is brought
        -- onto this FK-62 shape by ``postgres_store._reconcile_fact_tables_fk62``,
        -- which runs just BEFORE this script and DROPs (CASCADE) a ``fact_*`` table
        -- ONLY when its current column set differs from FK-62 — so an old table is
        -- dropped here and rebuilt FK-62-shaped (and the ``closed_at`` /
        -- ``period_start`` indexes below then apply cleanly), while an already-FK-62
        -- table is left intact (its recompute-disposable rollups are NOT wiped on
        -- every startup). The column-conditional DROP lives in Python (not this
        -- file) because ``iter_sql_statements`` cannot parse a ``DO $$`` body.
        CREATE TABLE IF NOT EXISTS fact_story (
            project_key                 TEXT NOT NULL,
            story_id                    TEXT NOT NULL,
            story_type                  TEXT NOT NULL,
            story_size                  TEXT NOT NULL,
            pipeline_mode               TEXT,
            opened_at                   TIMESTAMPTZ NOT NULL,
            closed_at                   TIMESTAMPTZ,
            processing_time_ms          BIGINT,
            compaction_count            BIGINT NOT NULL DEFAULT 0,
            qa_round_count              BIGINT NOT NULL DEFAULT 0,
            feedback_converged          BOOLEAN,
            blocked_ac_count            BIGINT NOT NULL DEFAULT 0,
            blocked_ac_detail_json      TEXT,
            llm_call_count              BIGINT NOT NULL DEFAULT 0,
            adversarial_findings_count  BIGINT NOT NULL DEFAULT 0,
            adversarial_tests_created   BIGINT NOT NULL DEFAULT 0,
            adversarial_hit_rate        DOUBLE PRECISION,
            findings_fully_resolved     BIGINT NOT NULL DEFAULT 0,
            findings_partially_resolved BIGINT NOT NULL DEFAULT 0,
            findings_not_resolved       BIGINT NOT NULL DEFAULT 0,
            final_status                TEXT,
            are_gate_passed             BOOLEAN,
            are_total_requirements      BIGINT,
            are_covered_requirements    BIGINT,
            files_changed               BIGINT NOT NULL DEFAULT 0,
            increment_count             BIGINT NOT NULL DEFAULT 0,
            phase_setup_ms              BIGINT,
            phase_exploration_ms        BIGINT,
            phase_implementation_ms     BIGINT,
            phase_verify_ms             BIGINT,
            phase_closure_ms            BIGINT,
            computed_at                 TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, story_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fact_story_project_closed
            ON fact_story (project_key, closed_at);

        CREATE TABLE IF NOT EXISTS fact_guard_period (
            project_key              TEXT NOT NULL,
            guard_key                TEXT NOT NULL,
            period_start             TIMESTAMPTZ NOT NULL,
            period_grain             TEXT NOT NULL DEFAULT 'week',
            invocation_count         BIGINT NOT NULL DEFAULT 0,
            violation_count          BIGINT NOT NULL DEFAULT 0,
            violation_rate           DOUBLE PRECISION,
            violation_stage_escape   BIGINT NOT NULL DEFAULT 0,
            violation_stage_schema   BIGINT NOT NULL DEFAULT 0,
            violation_stage_template BIGINT NOT NULL DEFAULT 0,
            escape_detection_count   BIGINT NOT NULL DEFAULT 0,
            computed_at              TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, guard_key, period_start)
        );

        CREATE INDEX IF NOT EXISTS idx_fact_guard_period_project_start
            ON fact_guard_period (project_key, period_start);

        CREATE TABLE IF NOT EXISTS fact_pool_period (
            project_key                  TEXT NOT NULL,
            pool_key                     TEXT NOT NULL,
            period_start                 TIMESTAMPTZ NOT NULL,
            period_grain                 TEXT NOT NULL DEFAULT 'week',
            call_count                   BIGINT NOT NULL DEFAULT 0,
            response_time_p50_ms         BIGINT,
            verdict_adopted_count        BIGINT NOT NULL DEFAULT 0,
            verdict_total_count          BIGINT NOT NULL DEFAULT 0,
            finding_true_positive_count  BIGINT NOT NULL DEFAULT 0,
            finding_false_positive_count BIGINT NOT NULL DEFAULT 0,
            quorum_triggered_count       BIGINT NOT NULL DEFAULT 0,
            template_finding_rate_json   TEXT,
            computed_at                  TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, pool_key, period_start)
        );

        CREATE INDEX IF NOT EXISTS idx_fact_pool_period_project_start
            ON fact_pool_period (project_key, period_start);

        CREATE TABLE IF NOT EXISTS fact_pipeline_period (
            project_key                         TEXT NOT NULL,
            period_start                        TIMESTAMPTZ NOT NULL,
            period_grain                        TEXT NOT NULL DEFAULT 'week',
            story_count                         BIGINT NOT NULL DEFAULT 0,
            story_count_closed                  BIGINT NOT NULL DEFAULT 0,
            execution_count                     BIGINT NOT NULL DEFAULT 0,
            exploration_count                   BIGINT NOT NULL DEFAULT 0,
            stage_miss_count                    BIGINT NOT NULL DEFAULT 0,
            stage_miss_detail_json              TEXT,
            impact_violation_count              BIGINT NOT NULL DEFAULT 0,
            impact_check_count                  BIGINT NOT NULL DEFAULT 0,
            integrity_gate_block_count          BIGINT NOT NULL DEFAULT 0,
            integrity_gate_total_count          BIGINT NOT NULL DEFAULT 0,
            doc_fidelity_conflict_by_level_json TEXT,
            first_pass_count                    BIGINT NOT NULL DEFAULT 0,
            finding_survival_count              BIGINT NOT NULL DEFAULT 0,
            finding_total_count                 BIGINT NOT NULL DEFAULT 0,
            effective_check_ids_json            TEXT,
            vectordb_total_hits                 BIGINT NOT NULL DEFAULT 0,
            vectordb_above_threshold            BIGINT NOT NULL DEFAULT 0,
            vectordb_classified_conflict        BIGINT NOT NULL DEFAULT 0,
            vectordb_duplicate_detected         BIGINT NOT NULL DEFAULT 0,
            processing_time_avg_ms              BIGINT,
            processing_time_variance_ms2        DOUBLE PRECISION,
            qa_round_avg                        DOUBLE PRECISION,
            computed_at                         TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, period_start)
        );

        CREATE TABLE IF NOT EXISTS fact_corpus_period (
            project_key                TEXT NOT NULL,
            period_start               TIMESTAMPTZ NOT NULL,
            period_grain               TEXT NOT NULL DEFAULT 'month',
            new_incident_count         BIGINT NOT NULL DEFAULT 0,
            patterns_total_count       BIGINT NOT NULL DEFAULT 0,
            patterns_with_active_check BIGINT NOT NULL DEFAULT 0,
            computed_at                TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, period_start)
        );

        -- FK-62 §62.2.7: project-scoped generic key-value sync cursor. NO global
        -- refresh pointer across projects (FK-62/FK-60). Known keys:
        -- last_event_id, last_synced_at, schema_version. value_int/value_text
        -- are the two payload slots; a given key uses exactly one.
        CREATE TABLE IF NOT EXISTS sync_state (
            project_key TEXT NOT NULL,
            key         TEXT NOT NULL,
            value_int   BIGINT,
            value_text  TEXT,
            updated_at  TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, key)
        );

        -- FK-62 §62.2.6 / FK-61 §61.4.3 scratchpad written from the hook
        -- hot-path; the RefreshWorker (follow-up story) drains it into
        -- fact_guard_period. Weekly key grain supports reset + weekly rollup;
        -- invocations/blocks are the violation-rate components.
        CREATE TABLE IF NOT EXISTS guard_invocation_counters (
            project_key TEXT NOT NULL,
            story_id    TEXT NOT NULL,
            guard_key   TEXT NOT NULL,
            week_start  TEXT NOT NULL,
            invocations BIGINT NOT NULL DEFAULT 0,
            blocks      BIGINT NOT NULL DEFAULT 0,
            updated_at  TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_key, story_id, guard_key, week_start)
        );
