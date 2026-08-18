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

        stage('Container Vulnerability Scan - Trivy') {
            steps {
                sh '''
                    echo "=== Trivy Image Scan ==="

                    APP_VERSION=$(cat VERSION)

                    docker run --rm \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        -v trivy-cache:/root/.cache/ \
                        aquasec/trivy:0.72.0 \
                        image \
                        --scanners vuln \
                        --severity HIGH,CRITICAL \
                        --ignore-unfixed \
                        --exit-code 1 \
                        deployment-tracker:"$APP_VERSION"
                '''
            }
        }

        stage('Generate SBOM - Syft') {
            steps {
                sh '''
                    echo "=== Generate CycloneDX SBOM ==="

                    APP_VERSION=$(cat VERSION)

                    mkdir -p reports

                    docker run --rm \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        anchore/syft:v1.50.0 \
                        deployment-tracker:"$APP_VERSION" \
                        -o cyclonedx-json \
                        > reports/sbom.cdx.json

                    test -s reports/sbom.cdx.json

                    echo "SBOM generated:"
                    ls -lh reports/sbom.cdx.json
                '''

                archiveArtifacts \
                    artifacts: 'reports/sbom.cdx.json',
                    fingerprint: true
            }
        }

        stage('Publish Image - GHCR') {
            steps {
                withCredentials([
                    string(
                        credentialsId: 'ghcr-token',
                        variable: 'GHCR_TOKEN'
                    )
                ]) {
                    sh '''
                        set +x
                        set -e

                        echo "=== Publish Image to GHCR ==="

                        APP_VERSION=$(cat VERSION)

                        LOCAL_IMAGE="deployment-tracker:$APP_VERSION"
                        REGISTRY_IMAGE="ghcr.io/iiismailtriki/deployment-tracker:$APP_VERSION"

                        mkdir -p reports

                        TEMP_DOCKER_CONFIG=$(mktemp -d)
                        export DOCKER_CONFIG="$TEMP_DOCKER_CONFIG"

                        cleanup() {
                            docker logout ghcr.io >/dev/null 2>&1 || true
                            rm -rf "$TEMP_DOCKER_CONFIG"
                        }

                        trap cleanup EXIT

                        echo "$GHCR_TOKEN" | \
                            docker login ghcr.io \
                            -u iiismailtriki \
                            --password-stdin

                        docker tag \
                            "$LOCAL_IMAGE" \
                            "$REGISTRY_IMAGE"

                        echo "=== Push Image ==="

                        PUSH_OUTPUT="$(docker push "$REGISTRY_IMAGE" 2>&1)"

                        echo "$PUSH_OUTPUT"

                        echo "=== Extract Published Digest ==="

                        IMAGE_DIGEST="$(echo "$PUSH_OUTPUT" \
                            | grep -oE 'digest: sha256:[0-9a-f]{64}' \
                            | tail -n 1 \
                            | awk '{print $2}')"

                        if [ -z "$IMAGE_DIGEST" ]; then
                            echo "ERROR: Could not determine pushed image digest."
                            exit 1
                        fi

                        if ! echo "$IMAGE_DIGEST" \
                            | grep -Eq '^sha256:[0-9a-f]{64}$'; then
                            echo "ERROR: Invalid image digest format."
                            exit 1
                        fi

                        echo "$IMAGE_DIGEST" > reports/image-digest.txt

                        test -s reports/image-digest.txt

                        echo "Published image:"
                        echo "$REGISTRY_IMAGE"

                        echo "Published digest:"
                        cat reports/image-digest.txt

                        echo "Immutable image reference:"
                        echo "ghcr.io/iiismailtriki/deployment-tracker@$IMAGE_DIGEST"
                    '''
                }

                archiveArtifacts \
                    artifacts: 'reports/image-digest.txt',
                    fingerprint: true
            }
        }
    }
}
