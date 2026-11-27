#!/usr/bin/env bash
# Deploy-test the hallucination-detector InferenceService on a local minikube profile.
# GKE stays the production target; this uses the same chart, runtime and namespace with
# infrastructure/k8s/values/model-minikube.yaml. Predictor only (see that file).
#
#   infrastructure/k8s/local/deploy-minikube.sh          # from the repo root
#   k9s --context viai-qa -n hallucination-prod           # browse it
set -euo pipefail
PROFILE="${PROFILE:-viai-qa}"
NS=hallucination-prod
K="kubectl --context $PROFILE"
H="helm --kube-context $PROFILE"
cd "$(git rev-parse --show-toplevel)"

echo "== cluster ($PROFILE; kubectl's default context is left alone)"
minikube status -p "$PROFILE" >/dev/null 2>&1 || \
  minikube start -p "$PROFILE" --driver=docker --memory=5g --cpus=4 --kubernetes-version=v1.34.0 --keep-context=true

echo "== cert-manager + KServe 0.16 (Standard mode: no Knative / Istio)"
helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
$H upgrade --install cert-manager jetstack/cert-manager --version v1.16.2 -n cert-manager --create-namespace \
  --set crds.enabled=true --wait --timeout 20m
$H upgrade --install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd --version v0.16.0 -n kserve --create-namespace --wait
$H upgrade --install kserve oci://ghcr.io/kserve/charts/kserve --version v0.16.0 -n kserve \
  --set kserve.controller.deploymentMode=Standard --set kserve.controller.gateway.disableIngressCreation=true \
  --wait --timeout 25m

echo "== predictor image (infrastructure/docker/Dockerfile.predictor) into the cluster"
docker build -t hallucination-predictor:local -f infrastructure/docker/Dockerfile.predictor infrastructure/docker
# `image load --overwrite` keeps a stale image under the same tag, so remove it first
minikube -p "$PROFILE" image rm hallucination-predictor:local >/dev/null 2>&1 || true
minikube -p "$PROFILE" image load hallucination-predictor:local
docker image inspect alpine:3.20 >/dev/null 2>&1 || docker pull alpine:3.20
minikube -p "$PROFILE" image load alpine:3.20

echo "== namespace, secrets the chart references (unused with a PVC), serving runtime"
$K apply -f infrastructure/k8s/namespace.yaml
for s in "mlflow-secret --from-literal=MLFLOW_TRACKING_URI=http://unused:5000 --from-literal=MLFLOW_S3_ENDPOINT_URL=http://unused:9000" \
         "aws-credentials --from-literal=AWS_ACCESS_KEY_ID=unused --from-literal=AWS_SECRET_ACCESS_KEY=unused"; do
  # shellcheck disable=SC2086
  $K -n $NS create secret generic $s --dry-run=client -o yaml | $K apply -f -
done
# swap the image before applying: apply-then-patch lets KServe start a pod pulling the multi-GB prod image
sed 's|image: docker.io/seldonio/mlserver:.*|image: hallucination-predictor:local|' \
  infrastructure/k8s/runtimes/mlflow-cluster-runtime.yaml | $K apply -f -

echo "== model: current folds -> MLflow pyfunc -> PVC (stands in for the S3/GCS bucket)"
python machine-learning/scripts/export_serving_model.py artifacts/local/serving-model
$K apply -f infrastructure/k8s/local/model-store.yaml
$K -n $NS wait pod/model-store-loader --for=condition=Ready --timeout=300s
$K -n $NS exec model-store-loader -- rm -rf /store/model
$K -n $NS cp artifacts/local/serving-model model-store-loader:/store/model
$K -n $NS delete pod model-store-loader --wait

echo "== InferenceService (hallucination-model chart)"
$H upgrade --install hallucination-model infrastructure/k8s/charts/hallucination-model -n $NS \
  -f infrastructure/k8s/values/model-minikube.yaml
# same tag, new image: recreate the pod (KServe's controller reverts `rollout restart` on its Deployment)
$K -n $NS delete pod -l serving.kserve.io/inferenceservice=hallucination-detector,component=predictor --ignore-not-found --wait=false
$K -n $NS wait inferenceservice/hallucination-detector --for=condition=Ready --timeout=15m
$K -n $NS get inferenceservice,pods
echo "Smoke test: $K -n $NS port-forward svc/hallucination-detector-predictor 18085:80"
