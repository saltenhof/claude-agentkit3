pipeline {
    agent any

    options {
        timeout(time: 90, unit: 'MINUTES')
        ansiColor('xterm')
        timestamps()
        disableConcurrentBuilds()
    }

    triggers {
        cron('H * * * *')
    }

    parameters {
        string(name: 'agentkit_mode', defaultValue: 'ci', description: 'AgentKit pipeline mode')
        string(name: 'sonar_project_key', defaultValue: 'claude-agentkit3', description: 'CP10d self-test Sonar project key')
        string(name: 'sonar_branch', defaultValue: 'main', description: 'CP10d self-test Sonar branch')
    }

    environment {
        PYTHONDONTWRITEBYTECODE = '1'
        PYTHONUNBUFFERED = '1'
    }

    stages {
        stage('CP10d Branch Plugin Self-Test') {
            when {
                expression { params.agentkit_mode == 'cp10d_branch_plugin_self_test' }
            }
            steps {
                deleteDir()
                withSonarQubeEnv('agentkit3-sonar') {
                    sh '''
                        set -eu
                        mkdir -p cp10d-fixture
                        cat > cp10d-fixture/sample.py <<'PY'
class Cp10dOversizedFixture:
PY
                        for i in $(seq 1 2200); do
                            printf '    value_%04d = "%s"\\n' "$i" "cp10d oversized fixture literal" >> cp10d-fixture/sample.py
                        done
                        cat >> cp10d-fixture/sample.py <<'PY'

    def read(self):
        return self.value_0001
PY
                        SCANNER_VERSION="$(sonar-scanner --version 2>&1 | awk '/SonarScanner/ {print $NF; exit}')"
                        sonar-scanner \
                            -Dsonar.projectKey="${sonar_project_key}" \
                            -Dsonar.projectName="${sonar_project_key}" \
                            -Dsonar.sources=cp10d-fixture \
                            -Dsonar.branch.name="${sonar_branch}" \
                            -Dsonar.qualitygate.wait=true
                        printf '%s\n' "$SCANNER_VERSION" > .scannerwork/sonar-scanner-version.txt
                    '''
                }
                archiveArtifacts artifacts: '.scannerwork/report-task.txt,.scannerwork/sonar-scanner-version.txt', allowEmptyArchive: false
            }
        }

        stage('Prepare') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                deleteDir()
                sh '''
                    rm -rf agentkit-src
                    git clone --depth 1 --branch main --single-branch https://github.com/saltenhof/claude-agentkit3.git agentkit-src
                    git -C agentkit-src rev-parse HEAD
                    git -C agentkit-src show --no-patch --oneline HEAD
                    grep -n "agentkit_postgres_schema_ddl" agentkit-src/src/agentkit/backend/state_backend/postgres_store.py
                '''
            }
        }

        stage('Setup') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        python3 -m venv .venv
                        . .venv/bin/activate
                        python -m pip install --quiet --upgrade pip
                        pip install --quiet -e ".[dev]"
                        mkdir -p test-results var/reports/sonar
                    '''
                }
            }
        }

        stage('Ruff') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        python -m ruff check src tests
                    '''
                }
            }
        }

        stage('Mypy') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        python -m mypy src --strict --no-error-summary
                    '''
                }
            }
        }

        stage('Unit Tests + Coverage') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        AGENTKIT_STATE_BACKEND=sqlite \
                        AGENTKIT_ALLOW_SQLITE=1 \
                        python -m pytest tests/unit \
                            -q \
                            --junitxml=test-results/ci.xml \
                            --cov=src \
                            --cov-report=xml:coverage.xml
                    '''
                }
            }
        }

        stage('Postgres Contract + Integration') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        set -eu
                        . .venv/bin/activate
                        DB_NAME="agentkit_test_${BUILD_NUMBER:-manual}"
                        # Force IPv4: this is a local Windows network with no routable IPv6.
                        # The dual-stack host.docker.internal name otherwise intermittently
                        # resolves to an unreachable IPv6 ULA (psycopg "Network is unreachable").
                        PG_HOST="$(getent ahostsv4 host.docker.internal | awk 'NR==1 {print $1}')"
                        : "${PG_HOST:?could not resolve host.docker.internal to an IPv4 address}"
                        export AGENTKIT_STATE_BACKEND=postgres
                        export AGENTKIT_STATE_DATABASE_URL="postgresql://agentkit:agentkit@${PG_HOST}:55432/${DB_NAME}"
                        export AGENTKIT_PG_ADMIN_DSN="postgresql://agentkit:agentkit@${PG_HOST}:55432/postgres"
                        python - <<'PY'
from __future__ import annotations

import time

import psycopg
from psycopg import sql

host_dsn = __import__("os").environ["AGENTKIT_PG_ADMIN_DSN"]
db_name = "agentkit_test_" + __import__("os").environ.get("BUILD_NUMBER", "manual")
deadline = time.time() + 60
last_error: Exception | None = None

while time.time() < deadline:
    try:
        with psycopg.connect(host_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                    (db_name,),
                )
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(db_name),
                    )
                )
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name))
                )
        break
    except psycopg.Error as exc:
        last_error = exc
        time.sleep(1)
else:
    raise SystemExit(
        "Postgres service at host.docker.internal:55432 not reachable "
        f"within 60s: {last_error!r}"
    )
PY
                        set +e
                        python -m pytest tests/contract tests/integration tests/e2e \
                            -m "not requires_gh" \
                            -q \
                            --junitxml=test-results/postgres.xml
                        TEST_EXIT=$?
                        set -e
                        python - <<'PY'
from __future__ import annotations

import os

import psycopg
from psycopg import sql

host_dsn = __import__("os").environ["AGENTKIT_PG_ADMIN_DSN"]
db_name = "agentkit_test_" + os.environ.get("BUILD_NUMBER", "manual")

with psycopg.connect(host_dsn, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (db_name,),
        )
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
        )
PY
                        exit "$TEST_EXIT"
                    '''
                }
            }
        }

        stage('Concept Frontmatter Lint') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        PYTHONPATH=src python scripts/ci/check_concept_frontmatter.py
                    '''
                }
            }
        }

        stage('Formal Spec Compile') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        PYTHONPATH=src python scripts/ci/compile_formal_specs.py
                    '''
                }
            }
        }

        stage('Concept Contract Checks') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        PYTHONPATH=src python scripts/ci/check_concept_code_contracts.py
                        PYTHONPATH=src python scripts/ci/check_architecture_conformance.py
                    '''
                }
            }
        }

        stage('LOC Analysis') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        python scripts/python/py_loc_to_sonar.py \
                            --output var/reports/sonar/python-loc-issues.json \
                            --base-dir . \
                            src
                    '''
                }
            }
        }

        stage('SonarQube') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    withSonarQubeEnv('agentkit3-sonar') {
                        sh 'sonar-scanner'
                    }
                }
            }
        }

        stage('Quality Gate') {
            when {
                expression { params.agentkit_mode != 'cp10d_branch_plugin_self_test' }
            }
            steps {
                dir('agentkit-src') {
                    withSonarQubeEnv('agentkit3-sonar') {
                        script {
                            int gateStatus = sh(
                                returnStatus: true,
                                script: '''
                                    . .venv/bin/activate
                                    python scripts/python/wait_for_sonar_quality_gate.py \
                                        --host "$SONAR_HOST_URL" \
                                        --project-key "claude-agentkit3" \
                                        --timeout-seconds 600
                                ''',
                            )
                            if (gateStatus != 0) {
                                error 'Sonar quality gate is red.'
                            }
                        }
                    }
                }
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'agentkit-src/test-results/*.xml'
            archiveArtifacts artifacts: 'agentkit-src/coverage.xml,agentkit-src/var/reports/sonar/*.json,agentkit-src/test-results/*.xml', allowEmptyArchive: true
            deleteDir()
        }
        success {
            echo 'AgentKit 3: Build + SonarQube clean'
        }
        failure {
            echo 'AgentKit 3: Build or quality gate failed'
        }
    }
}
