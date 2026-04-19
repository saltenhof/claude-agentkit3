pipeline {
    agent any

    options {
        timeout(time: 30, unit: 'MINUTES')
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
                    mkdir -p agentkit-src
                    tar \
                        --exclude=.git \
                        --exclude=.tmp \
                        --exclude=.venv \
                        --exclude=.pytest-temp* \
                        --exclude=.mypy_cache \
                        --exclude=.pytest_cache \
                        --exclude=.ruff_cache \
                        --exclude=.coverage \
                        --exclude=coverage.xml \
                        --exclude=reports \
                        --exclude=test-results \
                        -C /codebase/claude-agentkit3 \
                        -cf - . | tar -C agentkit-src -xf -
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
                        CONTAINER_NAME="ak3-ci-postgres-${BUILD_NUMBER:-manual}"
                        PORT=55432
                        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
                        trap 'docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true' EXIT
                        docker run -d --rm \
                            --name "$CONTAINER_NAME" \
                            -e POSTGRES_USER=agentkit \
                            -e POSTGRES_PASSWORD=agentkit \
                            -e POSTGRES_DB=agentkit_test \
                            -p ${PORT}:5432 \
                            postgres:17-alpine >/dev/null
                        for i in $(seq 1 60); do
                            if docker exec "$CONTAINER_NAME" pg_isready -U agentkit -d agentkit_test >/dev/null 2>&1; then
                                break
                            fi
                            sleep 1
                        done
                        . .venv/bin/activate
                        export AGENTKIT_STATE_BACKEND=postgres
                        export AGENTKIT_STATE_DATABASE_URL="postgresql://agentkit:agentkit@127.0.0.1:${PORT}/agentkit_test"
                        python -m pytest tests/contract tests/integration tests/e2e \
                            -m "not requires_gh" \
                            -q \
                            --junitxml=test-results/postgres.xml
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
                    withSonarQubeEnv('brainbox-sonar') {
                        sh 'sonar-scanner'
                    }
                }
            }
        }

        stage('Quality Gate') {
            steps {
                dir('agentkit-src') {
                    withSonarQubeEnv('brainbox-sonar') {
                        sh '''
                            . .venv/bin/activate
                            python scripts/python/wait_for_sonar_quality_gate.py \
                                --host "$SONAR_HOST_URL" \
                                --project-key "claude-agentkit3" \
                                --timeout-seconds 600
                        '''
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
