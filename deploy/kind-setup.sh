#!/usr/bin/env bash
# One-command local cluster + AgentAnvil deploy using kind.
#
# Prereqs: docker, kind, kubectl, helm (all on PATH).
#
# This script is intentionally linear and idempotent-ish — re-running it will
# attempt to reuse the existing cluster and skip steps that are already done.

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-agentanvil-dev}"
NAMESPACE="${NAMESPACE:-agentanvil}"
IMAGE_TAG="${IMAGE_TAG:-0.0.2}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Ensure kind cluster '${CLUSTER_NAME}' exists"
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    cat <<EOF | kind create cluster --name "${CLUSTER_NAME}" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30300
        hostPort: 30300
        protocol: TCP
EOF
else
    echo "    cluster already exists"
fi

echo "==> Build UI image"
docker build -t "agentanvil-ui:${IMAGE_TAG}" "${REPO_ROOT}/ui"

echo "==> Load image into kind"
kind load docker-image "agentanvil-ui:${IMAGE_TAG}" --name "${CLUSTER_NAME}"

echo "==> Create namespace ${NAMESPACE} (if needed)"
kubectl get ns "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

echo "==> Helm install / upgrade"
helm upgrade --install agentanvil "${REPO_ROOT}/deploy/helm/agentanvil" \
    --namespace "${NAMESPACE}" \
    --set image.tag="${IMAGE_TAG}" \
    --set traces.persistence.accessMode=ReadWriteOnce \
    --wait --timeout 180s

echo "==> Deployment ready"
kubectl --namespace "${NAMESPACE}" get pods,svc,pvc

cat <<EOF

To access the UI:
    kubectl --namespace ${NAMESPACE} port-forward svc/agentanvil 3001:80
    open http://localhost:3001

To tear down:
    kind delete cluster --name ${CLUSTER_NAME}
EOF
