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

        stage('Sign and Verify Image - Cosign') {
            steps {
                withCredentials([
                    file(
                        credentialsId: 'cosign-private-key',
                        variable: 'COSIGN_KEY_FILE'
                    ),
                    string(
                        credentialsId: 'cosign-password',
                        variable: 'COSIGN_PASSWORD'
                    ),
                    string(
                        credentialsId: 'ghcr-token',
                        variable: 'GHCR_TOKEN'
                    )
                ]) {
                    sh '''
                        set +x
                        set -e

                        echo "=== Cosign Sign + Verify ==="

                        echo "=== Validate required inputs ==="

                        test -s reports/image-digest.txt
                        test -s cosign.pub
                        test -s "$COSIGN_KEY_FILE"

                        IMAGE_DIGEST=$(cat reports/image-digest.txt)

                        if ! echo "$IMAGE_DIGEST" \
                            | grep -Eq '^sha256:[0-9a-f]{64}$'; then
                            echo "ERROR: Invalid image digest."
                            exit 1
                        fi

                        IMAGE_REF="ghcr.io/iiismailtriki/deployment-tracker@$IMAGE_DIGEST"

                        echo "Exact immutable image:"
                        echo "$IMAGE_REF"

                        echo "=== Create temporary key volume ==="

                        COSIGN_VOL=$(docker volume create)

                        cleanup() {
                            echo "Cleaning temporary Cosign key volume..."
                            docker volume rm -f "$COSIGN_VOL" \
                                >/dev/null 2>&1 || true
                        }

                        trap cleanup EXIT

                        echo "=== Copy private key into temporary volume ==="

                        docker run --rm -i \
                            -v "$COSIGN_VOL:/keys" \
                            alpine:3.20 \
                            sh -c 'umask 077; cat > /keys/cosign.key' \
                            < "$COSIGN_KEY_FILE"

                        echo "=== Copy public key into temporary volume ==="

                        docker run --rm -i \
                            -v "$COSIGN_VOL:/keys" \
                            alpine:3.20 \
                            sh -c 'cat > /keys/cosign.pub; chmod 0644 /keys/cosign.pub' \
                            < cosign.pub

                        echo "=== Sign exact image digest ==="

                        docker run --rm \
                            --user 0:0 \
                            -e HOME=/tmp \
                            -e COSIGN_PASSWORD \
                            -v "$COSIGN_VOL:/keys:ro" \
                            ghcr.io/sigstore/cosign/cosign:v3.0.6 \
                            sign \
                            --yes \
                            --key /keys/cosign.key \
                            --registry-username iiismailtriki \
                            --registry-password "$GHCR_TOKEN" \
                            "$IMAGE_REF"

                        echo "=== Verify image signature ==="

                        docker run --rm \
                            --user 0:0 \
                            -e HOME=/tmp \
                            -v "$COSIGN_VOL:/keys:ro" \
                            ghcr.io/sigstore/cosign/cosign:v3.0.6 \
                            verify \
                            --key /keys/cosign.pub \
                            --registry-username iiismailtriki \
                            --registry-password "$GHCR_TOKEN" \
                            "$IMAGE_REF"

                        echo "=== Cosign verification successful ==="
                    '''
                }
            }
        }

    }
}
