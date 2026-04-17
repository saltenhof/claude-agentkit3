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

        stage('Tests + Coverage') {
            steps {
                dir('agentkit-src') {
                    sh '''
                        . .venv/bin/activate
                        python -m pytest tests/unit tests/integration \
                            -q \
                            --junitxml=test-results/ci.xml \
                            --cov=src \
                            --cov-report=xml:coverage.xml
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
            junit allowEmptyResults: true, testResults: 'agentkit-src/test-results/ci.xml'
            archiveArtifacts artifacts: 'agentkit-src/coverage.xml,agentkit-src/reports/sonar/*.json,agentkit-src/test-results/ci.xml', allowEmptyArchive: true
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
