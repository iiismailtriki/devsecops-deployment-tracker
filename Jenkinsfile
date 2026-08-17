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
    }
}
