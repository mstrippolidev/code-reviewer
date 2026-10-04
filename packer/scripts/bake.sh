#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/code-reviewer
OVERLAY="$APP_DIR/k8s/overlays/single-node"
K3S_DATA=/var/lib/rancher/k3s

mkdir -p "$APP_DIR/k8s" "$APP_DIR/operators" /etc/code-reviewer
tar -xzf /tmp/k8s.tar.gz -C "$APP_DIR/k8s"
echo "extracted k8s tree:"
find "$APP_DIR/k8s" -maxdepth 2 -type d
install -m 0755 /tmp/boot.sh /usr/local/bin/code-reviewer-boot
install -m 0644 /tmp/code-reviewer-boot.service /etc/systemd/system/code-reviewer-boot.service
echo "ECR_REGISTRY=${ECR_REGISTRY}" > /etc/code-reviewer/boot.env

curl -sfL https://get.k3s.io | \
  INSTALL_K3S_CHANNEL="$K3S_CHANNEL" \
  INSTALL_K3S_EXEC="server --disable traefik --disable servicelb --disable metrics-server --write-kubeconfig-mode 644 --node-label workload=stateful" \
  sh -

for _ in $(seq 1 60); do
  k3s kubectl get nodes 2>/dev/null | grep -q " Ready" && break
  sleep 3
done
k3s kubectl get nodes | grep -q " Ready"

# The operator bundles are remote kustomize URLs; render them now so boot needs no internet.
for operator in strimzi cnpg; do
  k3s kubectl kustomize "$APP_DIR/k8s/operators/$operator" > "$APP_DIR/operators/$operator.yaml"
done

KAFKA_VERSION=$(awk '/^    version:/ {print $2; exit}' "$APP_DIR/k8s/base/kafka/kafka.yaml")
KAFKA_IMAGE=$(grep -ohE "quay.io/strimzi/kafka:[^\"[:space:]]*kafka-${KAFKA_VERSION}" "$APP_DIR/operators/strimzi.yaml" | head -1 || true)
if [ -z "$KAFKA_IMAGE" ]; then
  echo "strimzi bundle has no Kafka ${KAFKA_VERSION} image; align the Kafka CR version with the bundle" >&2
  exit 1
fi

# CRD schemas also contain "image:" keys with empty or {} values; keep only real references.
IMAGE_REF='^[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$'

{
  grep -hE '^\s+image:' "$APP_DIR"/operators/*.yaml | awk '{print $2}'
  echo "$KAFKA_IMAGE"
  k3s kubectl kustomize "$OVERLAY" | sed "s#<ECR_REGISTRY>#${ECR_REGISTRY}#g" \
    | grep -hE '^\s+(- )?(image|imageName):' | awk '{print $NF}'
} | tr -d '"' | grep -E "$IMAGE_REF" | sort -u > "$APP_DIR/images.txt"

echo "images to pre-pull:"
cat "$APP_DIR/images.txt"

qualify_ref() {
  local ref=$1 first=${1%%/*}
  if [[ "$ref" != */* ]]; then
    echo "docker.io/library/$ref"
  elif [[ "$first" == *.* || "$first" == *:* || "$first" == localhost ]]; then
    echo "$ref"
  else
    echo "docker.io/$ref"
  fi
}

while read -r raw_ref; do
  ref=$(qualify_ref "$raw_ref")
  if [[ "$ref" == "$ECR_REGISTRY"/* ]]; then
    k3s ctr -n k8s.io images pull --user "AWS:${ECR_PASSWORD}" "$ref"
  else
    k3s ctr -n k8s.io images pull "$ref"
  fi
done < "$APP_DIR/images.txt"

# A fresh instance must mint its own cluster identity: keep only the image store.
/usr/local/bin/k3s-killall.sh
rm -rf "$K3S_DATA/server" /etc/rancher/node /var/lib/kubelet
find "$K3S_DATA/agent" -mindepth 1 -maxdepth 1 ! -name containerd -exec rm -rf {} +

systemctl enable code-reviewer-boot.service
