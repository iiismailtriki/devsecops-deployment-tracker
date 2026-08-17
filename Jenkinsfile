pipeline {
    agent {
        label 'devsecops'
    }

    stages {
        stage('Environment') {
            steps {
                sh '''
                    echo "=== Python ==="
                    python3 --version

                    echo "=== Create virtual environment ==="
                    rm -rf .venv
                    python3 -m venv .venv

                    echo "=== Install dependencies ==="
                    .venv/bin/python -m pip install --upgrade pip
                    .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
                '''
            }
        }


        stage('Unit Tests') {
            steps {
                sh '''
                    echo "=== pytest ==="
                    .venv/bin/pytest -q
                '''
            }
        }

        stage('Code Quality - Ruff') {
            steps {
                sh '''
                    echo "=== Ruff ==="
                    .venv/bin/ruff check .
                '''
            }
        }

        stage('SAST - Bandit') {
            steps {
                sh '''
                    echo "=== Bandit ==="
                    .venv/bin/bandit -r app
                '''
            }
        }

        stage('Dependency Audit') {
            steps {
                sh '''
                    echo "=== pip-audit ==="
                    .venv/bin/pip-audit -r requirements.txt
                '''
            }
        }
        stage('Dockerfile Lint - Hadolint') {
            steps {
                sh '''
                    echo "=== Hadolint ==="
                    docker run --rm \
                        -i hadolint/hadolint:latest \
                        < Dockerfile
                '''
            }
        }

        stage('Docker Build') {
            steps {
                sh '''
                    echo "=== Docker Build ==="

                    APP_VERSION=$(cat VERSION)
                    VCS_REF=$(git rev-parse HEAD)
                    BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

                    docker build --pull \
                        --build-arg APP_VERSION="$APP_VERSION" \
                        --build-arg VCS_REF="$VCS_REF" \
                        --build-arg BUILD_DATE="$BUILD_DATE" \
                        -t deployment-tracker:"$APP_VERSION" \
                        .
                '''
            }
        }
    }
}
