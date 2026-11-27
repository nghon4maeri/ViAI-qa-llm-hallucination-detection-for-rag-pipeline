package main

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
)

// recorder is a Runner that records every command and answers Output calls from a table.
type recorder struct {
	calls   []string
	outputs map[string]string // prefix of "name args..." -> stdout
	fail    map[string]bool   // prefix -> Output returns an error
}

func (r *recorder) line(name string, args []string) string {
	return strings.TrimSpace(name + " " + strings.Join(args, " "))
}

func (r *recorder) Run(_ context.Context, name string, args ...string) error {
	r.calls = append(r.calls, r.line(name, args))
	return nil
}

func (r *recorder) Output(_ context.Context, name string, args ...string) (string, error) {
	l := r.line(name, args)
	for p := range r.fail {
		if strings.HasPrefix(l, p) {
			return "", errors.New("not found")
		}
	}
	for p, out := range r.outputs {
		if strings.HasPrefix(l, p) {
			return out, nil
		}
	}
	return "", nil
}

func newTest(env string, rec *recorder) Deployer {
	cfg := Config{Profile: "viai-qa", Env: env, Root: "/repo", Memory: "5g", CPUs: "4", Python: "python"}
	return Deployer{cfg: cfg, run: rec, log: func(string, ...any) {}}
}

func TestCheckContext(t *testing.T) {
	gke := "gke_vihallu-llm-detect_asia-southeast1-a_vihallu-cluster"
	cases := []struct {
		profile, env string
		allow        bool
		ok           bool
	}{
		{"viai-qa", "local", false, true},
		{gke, "local", false, false}, // never by accident
		{gke, "prod", false, false},  // still needs the explicit flag
		{gke, "local", true, false},  // cloud needs --env prod too
		{gke, "prod", true, true},
		{"viai-qa", "prod", false, false},
	}
	for _, c := range cases {
		err := Config{Profile: c.profile, Env: c.env, AllowCloud: c.allow}.checkContext()
		if (err == nil) != c.ok {
			t.Errorf("profile=%s env=%s allow=%v: err=%v, want ok=%v", c.profile, c.env, c.allow, err, c.ok)
		}
	}
}

const rendered = `apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      initContainers:
        - name: init
          image: "busybox:1.36"
      containers:
        - name: api
          image: hallucination-backend-lite:local
        - name: sidecar
          image: docker.io/grafana/promtail:2.9.3
---
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
spec:
  version: v2.48.1
---
kind: Deployment
spec:
  template:
    spec:
      containers:
        - args:
            - --prometheus-config-reloader=quay.io/prometheus-operator/prometheus-config-reloader:v0.70.0
          image: quay.io/prometheus-operator/prometheus-operator:v0.70.0
---
kind: Pod
metadata:
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - image: bats/bats:1.8.2
`

func TestImagesFromManifests(t *testing.T) {
	got := ImagesFromManifests(rendered)
	want := []string{
		"busybox:1.36",
		"docker.io/grafana/promtail:2.9.3",
		"quay.io/prometheus-operator/prometheus-config-reloader:v0.70.0",
		"quay.io/prometheus-operator/prometheus-operator:v0.70.0",
		"quay.io/prometheus/prometheus:v2.48.1",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v\nwant %v", got, want) // local image and helm test hook left out
	}
}

func TestMissingNormalizesRefs(t *testing.T) {
	wanted := []string{"docker.io/grafana/promtail:2.9.3", "grafana/loki:2.6.1", "registry.k8s.io/x/controller:v1@sha256:abc", "nginx"}
	present := []string{"grafana/promtail:2.9.3", "registry.k8s.io/x/controller:v1", "nginx:latest"}
	if got := missing(wanted, present); !reflect.DeepEqual(got, []string{"grafana/loki:2.6.1"}) {
		t.Fatalf("got %v", got)
	}
}

func TestAllRunsStepsInOrderWithExplicitContext(t *testing.T) {
	rec := &recorder{
		outputs: map[string]string{
			"minikube status": "Running",
			"helmfile":        rendered,
			"minikube -p viai-qa ssh -- docker images": "grafana/promtail:2.9.3\nbusybox:1.36\n",
		},
		fail: map[string]bool{"kubectl --context viai-qa -n hallucination-prod get secret": true},
	}
	if err := newTest("local", rec).Step(context.Background(), "all", ""); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(rec.calls, "\n")
	// order: addons -> images -> preload -> secrets -> model -> sync -> status
	order := []string{"helm --kube-context viai-qa upgrade --install cert-manager", "docker build -q -t hallucination-predictor:local",
		"minikube -p viai-qa ssh -- docker pull -q quay.io/prometheus/prometheus:v2.48.1", "create secret generic mlflow-secret",
		"export_serving_model.py", "helmfile --file /repo/infrastructure/k8s/helmfile.yaml.gotmpl -e local --kube-context viai-qa sync",
		"kubectl --context viai-qa get nodes"}
	last := -1
	for _, o := range order {
		i := strings.Index(joined, o)
		if i < 0 || i < last {
			t.Fatalf("%q missing or out of order in:\n%s", o, joined)
		}
		last = i
	}
	if strings.Contains(joined, "minikube start") {
		t.Error("cluster already running: must not start it again")
	}
	if strings.Contains(joined, "docker pull -q grafana/promtail") || strings.Contains(joined, "docker pull -q busybox") {
		t.Error("images already on the node must not be pulled")
	}
	for _, c := range rec.calls {
		if (strings.HasPrefix(c, "kubectl ") && !strings.HasPrefix(c, "kubectl --context viai-qa")) ||
			(strings.HasPrefix(c, "helm upgrade") || strings.Contains(c, "use-context")) {
			t.Errorf("command without an explicit context or touching the default: %s", c)
		}
	}
}

func TestProdSkipsLocalOnlySteps(t *testing.T) {
	rec := &recorder{outputs: map[string]string{}}
	d := newTest("prod", rec)
	for _, s := range []string{"up", "images", "preload", "secrets", "model"} {
		if err := d.Step(context.Background(), s, ""); err != nil {
			t.Fatal(err)
		}
	}
	if len(rec.calls) != 0 {
		t.Fatalf("prod must leave cluster, images, secrets and model to Terraform / CI / MLflow, ran: %v", rec.calls)
	}
}

func TestAdoptOnlyTouchesUnownedObjects(t *testing.T) {
	rec := &recorder{
		outputs: map[string]string{
			"kubectl --context viai-qa get namespace hallucination-prod": "",           // exists, not owned
			"kubectl --context viai-qa get namespace monitoring":         "namespaces", // already owned
		},
		fail: map[string]bool{"kubectl --context viai-qa get clusterservingruntime": true}, // absent
	}
	if err := newTest("local", rec).Adopt(context.Background()); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(rec.calls, "\n")
	if !strings.Contains(joined, "annotate namespace hallucination-prod meta.helm.sh/release-name=namespaces") {
		t.Errorf("unowned namespace not adopted:\n%s", joined)
	}
	if strings.Contains(joined, "monitoring") || strings.Contains(joined, "clusterservingruntime") {
		t.Errorf("owned or absent objects must be left alone:\n%s", joined)
	}
}

func TestSyncSelector(t *testing.T) {
	rec := &recorder{}
	_ = newTest("local", rec).Sync(context.Background(), "tier=app")
	if want := "helmfile --file /repo/infrastructure/k8s/helmfile.yaml.gotmpl -e local --kube-context viai-qa -l tier=app sync"; rec.calls[0] != want {
		t.Fatalf("got %q", rec.calls[0])
	}
}
