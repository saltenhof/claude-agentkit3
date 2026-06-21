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

    environment {
        PYTHONDONTWRITEBYTECODE = '1'
        PYTHONUNBUFFERED = '1'
    }

    stages {
        stage('Prepare') {
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
            steps {
                dir('agentkit-src') {
                    sh '''
                        python3 -m venv .venv
                        . .venv/bin/activate
                        python -m pip install --quiet --upgrade pip
                        pip install --quiet -e ".[dev]"
                        mkdir -p test-results reports/sonar
                    '''
                }
            }
        }

        stage('Ruff') {
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
            steps {
                dir('agentkit-src') {
                    sh '''
                        set -eu
                        . .venv/bin/activate
                        DB_NAME="agentkit_test_${BUILD_NUMBER:-manual}"
                        export AGENTKIT_STATE_BACKEND=postgres
                        export AGENTKIT_STATE_DATABASE_URL="postgresql://agentkit:agentkit@host.docker.internal:55432/${DB_NAME}"
                        python - <<'PY'
from __future__ import annotations

import time

import psycopg
from psycopg import sql

host_dsn = "postgresql://agentkit:agentkit@host.docker.internal:55432/postgres"
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

host_dsn = "postgresql://agentkit:agentkit@host.docker.internal:55432/postgres"
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
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        python scripts/python/py_loc_to_sonar.py \
                            --output reports/sonar/python-loc-issues.json \
                            --base-dir . \
                            src
                    '''
                }
            }
        }

        stage('SonarQube') {
            steps {
                dir('agentkit-src') {
                    withSonarQubeEnv('agentkit3-sonar') {
                        sh 'sonar-scanner'
                    }
                }
            }
        }

        stage('Quality Gate') {
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
            archiveArtifacts artifacts: 'agentkit-src/coverage.xml,agentkit-src/reports/sonar/*.json,agentkit-src/test-results/*.xml', allowEmptyArchive: true
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
