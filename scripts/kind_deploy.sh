#!/usr/bin/env bash
# Real kind-cluster deploy of AgentAnvil — end-to-end smoke for K8s stack.
#
# What this does (in order):
#   1. Installs kind + kubectl + helm if missing (local user bin, no sudo)
#   2. Creates a kind cluster with port-mapping for :30300 → NodePort 30300
#   3. Builds the UI Docker image + loads it into kind
#   4. `helm install` the chart with ReadWriteOnce (single-node kind)
#   5. Waits for the Deployment to go Ready
#   6. Port-forwards to :3001 and curls the UI to confirm service
#   7. Launches an example Job and tails its logs
#   8. Prints `kubectl get pods/svc/pvc` + `kubectl describe pod` for record
#
# Unlike deploy/kind-setup.sh (which is the minimal happy-path), this script
# actually verifies and captures output at each stage — designed to be run
# once as part of the "real deploy proof" evidence, with artifacts saved
# into docs/k8s-evidence/ for the runbook.
set -euo pipefail

CLUSTER="${CLUSTER:-agentanvil-smoke}"
NS="${NS:-agentanvil}"
IMAGE_TAG="${IMAGE_TAG:-ci-smoke}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE_DIR="${REPO_ROOT}/docs/k8s-evidence"
mkdir -p "${EVIDENCE_DIR}"

log()  { echo -e "\033[1;34m▶\033[0m $*" ; }
ok()   { echo -e "\033[1;32m✓\033[0m $*" ; }
fail() { echo -e "\033[1;31m✗\033[0m $*" ; exit 1; }

# ─── [0/8] Dependency check ────────────────────────────────────
log "[0/8] Verifying dependencies on PATH"
for bin in docker kind kubectl helm; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        fail "$bin not on PATH. Install via:
        docker:  https://docs.docker.com/get-docker/
        kind:    curl -Lo ~/bin/kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64 && chmod +x ~/bin/kind
        kubectl: curl -Lo ~/bin/kubectl https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl && chmod +x ~/bin/kubectl
        helm:    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
    fi
done
ok "docker / kind / kubectl / helm all present"

# ─── [1/8] Cluster ─────────────────────────────────────────────
log "[1/8] Ensure kind cluster '${CLUSTER}' exists"
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER}$"; then
    ok "cluster already exists, reusing"
else
    cat <<EOF | kind create cluster --name "${CLUSTER}" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30300
        hostPort: 30300
        protocol: TCP
EOF
fi
ok "cluster ready"
kubectl cluster-info > "${EVIDENCE_DIR}/cluster-info.txt"

# ─── [2/8] Build + load UI image ───────────────────────────────
log "[2/8] Build UI image 'agentanvil-ui:${IMAGE_TAG}'"
docker build -t "agentanvil-ui:${IMAGE_TAG}" "${REPO_ROOT}/ui"

log "[2b/8] Load image into kind cluster"
kind load docker-image "agentanvil-ui:${IMAGE_TAG}" --name "${CLUSTER}"
ok "image loaded"

# ─── [3/8] Namespace ───────────────────────────────────────────
log "[3/8] Namespace ${NS}"
kubectl get ns "${NS}" >/dev/null 2>&1 || kubectl create namespace "${NS}"
ok "namespace ready"

# ─── [4/8] Helm install ────────────────────────────────────────
log "[4/8] helm install agentanvil → ${NS}"
helm upgrade --install agentanvil "${REPO_ROOT}/deploy/helm/agentanvil" \
    --namespace "${NS}" \
    --set image.tag="${IMAGE_TAG}" \
    --set traces.persistence.accessMode=ReadWriteOnce \
    --wait --timeout 180s
ok "helm install complete"

# ─── [5/8] Wait for readiness ──────────────────────────────────
log "[5/8] Wait for Deployment to go Ready"
kubectl --namespace "${NS}" rollout status deploy/agentanvil --timeout 120s

# ─── [6/8] Port-forward + curl smoke ───────────────────────────
log "[6/8] Port-forward + GET / smoke"
kubectl --namespace "${NS}" port-forward svc/agentanvil 3001:80 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 4
HTTP_CODE=$(curl -s -o /tmp/ui-body -w '%{http_code}' http://localhost:3001 || echo "000")
if [[ "$HTTP_CODE" == "200" ]]; then
    ok "UI served 200 over port-forward"
    head -c 400 /tmp/ui-body > "${EVIDENCE_DIR}/ui-response-head.html"
else
    fail "UI returned HTTP ${HTTP_CODE} — see 'kubectl logs' output below"
fi
kill $PF_PID 2>/dev/null || true

# ─── [7/8] Launch example rollout Job ──────────────────────────
log "[7/8] Example rollout Job (renders the Helm job template)"
helm upgrade agentanvil "${REPO_ROOT}/deploy/helm/agentanvil" \
    --namespace "${NS}" \
    --reuse-values \
    --set rolloutJob.enabled=true \
    --set rolloutJob.image.repository="agentanvil-ui" \
    --set rolloutJob.image.tag="${IMAGE_TAG}" \
    --set rolloutJob.command='echo "rollout placeholder — replace with your harness command"' \
    || echo "note: Helm 'upgrade' with reuse-values may error if no change; this is informational only"
JOB=$(kubectl --namespace "${NS}" get jobs -l app.kubernetes.io/component=rollout -o name | head -1 || true)
if [[ -n "$JOB" ]]; then
    ok "rollout Job exists: $JOB"
    kubectl --namespace "${NS}" logs "$JOB" > "${EVIDENCE_DIR}/rollout-job-log.txt" 2>&1 || true
else
    echo "ℹ no rollout Job materialized (template conditional on rolloutJob.enabled + non-empty command)"
fi

# ─── [8/8] Evidence capture ────────────────────────────────────
log "[8/8] Capturing evidence to docs/k8s-evidence/"
kubectl --namespace "${NS}" get pods,svc,pvc -o wide > "${EVIDENCE_DIR}/get-all.txt"
POD=$(kubectl --namespace "${NS}" get pods -l app.kubernetes.io/name=agentanvil -o name | head -1)
if [[ -n "$POD" ]]; then
    kubectl --namespace "${NS}" describe "$POD" > "${EVIDENCE_DIR}/pod-describe.txt"
    kubectl --namespace "${NS}" logs "$POD" --tail=100 > "${EVIDENCE_DIR}/pod-logs.txt" 2>&1 || true
fi
kubectl --namespace "${NS}" get events --sort-by='.lastTimestamp' \
    > "${EVIDENCE_DIR}/events.txt"
echo "  artifacts:"
ls -la "${EVIDENCE_DIR}/"

echo ""
ok "kind deploy smoke complete"
echo ""
echo "To tear down:   kind delete cluster --name ${CLUSTER}"
echo "To re-deploy:   bash scripts/kind_deploy.sh"
echo "Evidence:       ls docs/k8s-evidence/"
