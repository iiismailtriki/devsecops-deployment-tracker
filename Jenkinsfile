pipeline {
    agent {
        label 'devsecops'
    }

    stages {
        stage('Secret Scan - Gitleaks') {
            steps {
                sh '''
                    set -eu

                    echo "=== Gitleaks Secret Scan ==="

                    mkdir -p reports
                    rm -f reports/gitleaks.json

                    GITLEAKS_VOL="gitleaks-${BUILD_NUMBER}-$$"

                    cleanup() {
                        docker volume rm -f "$GITLEAKS_VOL" >/dev/null 2>&1 || true
                    }

                    trap cleanup 0

                    echo "=== Create temporary Gitleaks volume ==="
                    docker volume create "$GITLEAKS_VOL" >/dev/null

                    echo "=== Copy repository + Git history ==="

                    tar \
                        --exclude='./.venv' \
                        --exclude='./reports' \
                        -cf - . \
                    | docker run --rm -i \
                        -v "$GITLEAKS_VOL:/repo" \
                        alpine:3.20 \
                        tar -xf - -C /repo

                    echo "=== Prepare report directory ==="

                    docker run --rm \
                        -v "$GITLEAKS_VOL:/repo" \
                        alpine:3.20 \
                        mkdir -p /repo/reports

                    echo "=== Scan complete Git history ==="

                    set +e

                    docker run --rm \
                        -v "$GITLEAKS_VOL:/repo" \
                        -w /repo \
                        ghcr.io/gitleaks/gitleaks:v8.30.1 \
                        git \
                        --redact \
                        --no-banner \
                        --report-format json \
                        --report-path /repo/reports/gitleaks.json \
                        /repo

                    GITLEAKS_STATUS=$?

                    set -e

                    echo "=== Retrieve Gitleaks report ==="

                    if docker run --rm \
                        -v "$GITLEAKS_VOL:/repo:ro" \
                        alpine:3.20 \
                        test -f /repo/reports/gitleaks.json
                    then
                        docker run --rm \
                            -v "$GITLEAKS_VOL:/repo:ro" \
                            alpine:3.20 \
                            cat /repo/reports/gitleaks.json \
                            > reports/gitleaks.json
                    else
                        echo "ERROR: Gitleaks report was not generated."
                        exit 2
                    fi

                    test -s reports/gitleaks.json

                    echo "Gitleaks report:"
                    ls -lh reports/gitleaks.json

                    if [ "$GITLEAKS_STATUS" -ne 0 ]; then
                        echo "ERROR: Gitleaks detected a secret or encountered an error."
                        exit "$GITLEAKS_STATUS"
                    fi

                    echo "=== Gitleaks secret scan successful ==="
                '''
            }

            post {
                always {
                    archiveArtifacts(
                        artifacts: 'reports/gitleaks.json',
                        allowEmptyArchive: true,
                        fingerprint: true
                    )
                }
            }
        }

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

                    mkdir -p reports

                    BUILDX_METADATA_PROVENANCE=max docker buildx build --load --pull --metadata-file reports/build-metadata.json \
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

                        set +e
                        PUSH_OUTPUT="$(docker push "$REGISTRY_IMAGE" 2>&1)"
                        PUSH_STATUS=$?
                        set -e

                        printf '%s\n' "$PUSH_OUTPUT"

                        if [ "$PUSH_STATUS" -ne 0 ]; then
                            echo "ERROR: Docker push to GHCR failed with exit code $PUSH_STATUS."
                            exit "$PUSH_STATUS"
                        fi

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


        stage('Attest and Verify SBOM - Cosign') {
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

                        echo "=== Cosign SBOM Attestation + Verification ==="

                        echo "=== Validate required inputs ==="

                        test -s reports/image-digest.txt
                        test -s reports/sbom.cdx.json
                        test -s cosign.pub
                        test -s "$COSIGN_KEY_FILE"

                        IMAGE_DIGEST=$(cat reports/image-digest.txt)

                        if ! echo "$IMAGE_DIGEST" \
                            | grep -Eq '^sha256:[0-9a-f]{64}$'; then
                            echo "ERROR: Invalid image digest."
                            exit 1
                        fi

                        IMAGE_REF="ghcr.io/iiismailtriki/deployment-tracker@$IMAGE_DIGEST"

                        echo "Attesting SBOM for:"
                        echo "$IMAGE_REF"

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

                        echo "=== Copy SBOM into temporary volume ==="

                        docker run --rm -i \
                            -v "$COSIGN_VOL:/keys" \
                            alpine:3.20 \
                            sh -c 'cat > /keys/sbom.cdx.json; chmod 0644 /keys/sbom.cdx.json' \
                            < reports/sbom.cdx.json

                        echo "=== Create signed SBOM attestation ==="

                        docker run --rm \
                            --user 0:0 \
                            -e HOME=/tmp \
                            -e COSIGN_PASSWORD \
                            -v "$COSIGN_VOL:/keys:ro" \
                            ghcr.io/sigstore/cosign/cosign:v3.0.6 \
                            attest \
                            --yes \
                            --key /keys/cosign.key \
                            --predicate /keys/sbom.cdx.json \
                            --type cyclonedx \
                            --registry-username iiismailtriki \
                            --registry-password "$GHCR_TOKEN" \
                            "$IMAGE_REF"

                        echo "=== Verify SBOM attestation ==="

                        docker run --rm \
                            --user 0:0 \
                            -e HOME=/tmp \
                            -v "$COSIGN_VOL:/keys:ro" \
                            ghcr.io/sigstore/cosign/cosign:v3.0.6 \
                            verify-attestation \
                            --key /keys/cosign.pub \
                            --type cyclonedx \
                            --registry-username iiismailtriki \
                            --registry-password "$GHCR_TOKEN" \
                            "$IMAGE_REF" \
                            > reports/sbom-attestation-verification.json

                        test -s reports/sbom-attestation-verification.json

                        echo "Attestation verification evidence saved:"
                        ls -lh reports/sbom-attestation-verification.json

                        echo "=== SBOM attestation verification successful ==="
                    '''
                }

                archiveArtifacts(
                    artifacts: 'reports/sbom-attestation-verification.json',
                    fingerprint: true
                )
            }
        }


        stage('Attest and Verify Provenance - Cosign') {
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
                        set -eu

                        echo "=== Cosign Build Provenance Attestation + Verification ==="

                        test -s reports/build-metadata.json
                        test -s reports/image-digest.txt
                        test -s cosign.pub

                        IMAGE_DIGEST="$(cat reports/image-digest.txt)"

                        case "$IMAGE_DIGEST" in
                            sha256:*) ;;
                            *)
                                echo "ERROR: Invalid image digest."
                                exit 1
                                ;;
                        esac

                        IMAGE_REF="ghcr.io/iiismailtriki/deployment-tracker@${IMAGE_DIGEST}"

                        echo "Exact image:"
                        echo "$IMAGE_REF"

                        echo "=== Extract BuildKit provenance ==="

                        python3 - <<'PYTHON'
import json
from pathlib import Path

metadata_file = Path("reports/build-metadata.json")
provenance_file = Path("reports/provenance.json")

metadata = json.loads(metadata_file.read_text())

provenance = metadata.get("buildx.build.provenance")

if not isinstance(provenance, dict):
    raise SystemExit(
        "ERROR: buildx.build.provenance is missing."
    )

required = {
    "builder",
    "buildType",
    "materials",
    "invocation",
    "buildConfig",
    "metadata",
}

missing = sorted(required - provenance.keys())

if missing:
    raise SystemExit(
        "ERROR: Missing provenance fields: "
        + ", ".join(missing)
    )

provenance_file.write_text(
    json.dumps(
        provenance,
        indent=2,
        sort_keys=True
    ) + "\\n"
)

print("Provenance extracted successfully.")
PYTHON

                        test -s reports/provenance.json

                        echo "Provenance predicate:"
                        ls -lh reports/provenance.json

                        COSIGN_VOL="cosign-provenance-${BUILD_NUMBER}-$$"

                        cleanup() {
                            echo "Cleaning temporary provenance volume..."
                            docker volume rm -f "$COSIGN_VOL" >/dev/null 2>&1 || true
                        }

                        trap cleanup 0

                        echo "=== Create temporary Cosign volume ==="

                        docker volume create "$COSIGN_VOL" >/dev/null

                        echo "=== Copy private key ==="

                        docker run --rm -i \
                            -v "$COSIGN_VOL:/keys" \
                            alpine:3.20 \
                            sh -c 'umask 077; cat > /keys/cosign.key' \
                            < "$COSIGN_KEY_FILE"

                        echo "=== Copy public key ==="

                        docker run --rm -i \
                            -v "$COSIGN_VOL:/keys" \
                            alpine:3.20 \
                            sh -c 'cat > /keys/cosign.pub; chmod 0644 /keys/cosign.pub' \
                            < cosign.pub

                        echo "=== Copy provenance predicate ==="

                        docker run --rm -i \
                            -v "$COSIGN_VOL:/keys" \
                            alpine:3.20 \
                            sh -c 'cat > /keys/provenance.json; chmod 0644 /keys/provenance.json' \
                            < reports/provenance.json

                        echo "=== Attest SLSA provenance ==="

                        docker run --rm \
                            -e COSIGN_PASSWORD="$COSIGN_PASSWORD" \
                            -v "$COSIGN_VOL:/keys:ro" \
                            ghcr.io/sigstore/cosign/cosign:v3.0.6 \
                            attest \
                            --yes \
                            --key /keys/cosign.key \
                            --predicate /keys/provenance.json \
                            --type slsaprovenance02 \
                            --registry-username iiismailtriki \
                            --registry-password "$GHCR_TOKEN" \
                            "$IMAGE_REF"

                        echo "=== Verify SLSA provenance attestation ==="

                        docker run --rm \
                            -v "$COSIGN_VOL:/keys:ro" \
                            ghcr.io/sigstore/cosign/cosign:v3.0.6 \
                            verify-attestation \
                            --key /keys/cosign.pub \
                            --type slsaprovenance02 \
                            --registry-username iiismailtriki \
                            --registry-password "$GHCR_TOKEN" \
                            "$IMAGE_REF" \
                            > reports/provenance-attestation-verification.json

                        test -s reports/provenance-attestation-verification.json

                        echo "Verification evidence:"
                        ls -lh reports/provenance-attestation-verification.json

                        echo "=== Build provenance attestation verification successful ==="
                    '''
                }
            }

            post {
                always {
                    archiveArtifacts(
                        artifacts: 'reports/build-metadata.json,reports/provenance.json,reports/provenance-attestation-verification.json',
                        allowEmptyArchive: true,
                        fingerprint: true
                    )
                }
            }
        }

    }
}
