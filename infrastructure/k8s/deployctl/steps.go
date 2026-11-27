package main

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"time"
)

const ns = "hallucination-prod"

// Deployer runs the steps of a local (or, with --allow-cloud, GKE) deploy through a Runner.
type Deployer struct {
	cfg Config
	run Runner
	log func(format string, a ...any)
}

func (d Deployer) kubectl(ctx context.Context, args ...string) error {
	return d.run.Run(ctx, "kubectl", append([]string{"--context", d.cfg.Context()}, args...)...)
}

func (d Deployer) helm(ctx context.Context, args ...string) error {
	return d.run.Run(ctx, "helm", append([]string{"--kube-context", d.cfg.Context()}, args...)...)
}

// Up starts the minikube profile if it is not running. kubectl's default context is left alone.
func (d Deployer) Up(ctx context.Context) error {
	if d.cfg.Env != "local" {
		d.log("env %s: cluster is provisioned by Terraform, skipping", d.cfg.Env)
		return nil
	}
	if out, err := d.run.Output(ctx, "minikube", "status", "-p", d.cfg.Profile, "--format", "{{.APIServer}}"); err == nil && strings.TrimSpace(out) == "Running" {
		d.log("cluster %s is running", d.cfg.Profile)
		return nil
	}
	return d.run.Run(ctx, "minikube", "start", "-p", d.cfg.Profile, "--driver=docker",
		"--memory="+d.cfg.Memory, "--cpus="+d.cfg.CPUs, "--kubernetes-version="+k8sVersion, "--keep-context=true")
}

// Addons installs the cluster add-ons the helmfile assumes: cert-manager and KServe (Standard mode).
func (d Deployer) Addons(ctx context.Context) error {
	if err := d.run.Run(ctx, "helm", "repo", "add", "jetstack", "https://charts.jetstack.io", "--force-update"); err != nil {
		return err
	}
	steps := [][]string{
		{"upgrade", "--install", "cert-manager", "jetstack/cert-manager", "--version", certManagerVersion,
			"-n", "cert-manager", "--create-namespace", "--set", "crds.enabled=true", "--wait", "--timeout", "20m"},
		{"upgrade", "--install", "kserve-crd", "oci://ghcr.io/kserve/charts/kserve-crd", "--version", kserveVersion,
			"-n", "kserve", "--create-namespace", "--wait"},
		{"upgrade", "--install", "kserve", "oci://ghcr.io/kserve/charts/kserve", "--version", kserveVersion, "-n", "kserve",
			"--set", "kserve.controller.deploymentMode=Standard", "--set", "kserve.controller.gateway.disableIngressCreation=true",
			"--wait", "--timeout", "25m"},
	}
	for _, s := range steps {
		if err := d.helm(ctx, s...); err != nil {
			return err
		}
	}
	return nil
}

// Images builds the local images and loads them into the cluster. `minikube image load` keeps a
// stale image under the same tag, so each one is removed first.
func (d Deployer) Images(ctx context.Context) error {
	if d.cfg.Env != "local" {
		d.log("env %s: images come from GHCR (CI build job), skipping", d.cfg.Env)
		return nil
	}
	for _, img := range localImages {
		if err := d.run.Run(ctx, "docker", "build", "-q", "-t", img.Tag, "-f", filepath.Join(d.cfg.Root, img.Dockerfile),
			filepath.Join(d.cfg.Root, img.Context)); err != nil {
			return err
		}
		if err := d.load(ctx, img.Tag); err != nil {
			return err
		}
	}
	for _, img := range hostImages {
		if _, err := d.run.Output(ctx, "docker", "image", "inspect", img); err != nil {
			continue // not on the host: preload pulls it inside the cluster
		}
		if err := d.load(ctx, img); err != nil {
			return err
		}
	}
	return nil
}

func (d Deployer) load(ctx context.Context, tag string) error {
	_ = d.run.Run(ctx, "minikube", "-p", d.cfg.Profile, "image", "rm", tag) // absent the first time
	return d.run.Run(ctx, "minikube", "-p", d.cfg.Profile, "image", "load", tag)
}

// Preload pulls every public image the helmfile releases need before `sync`. helmfile installs
// with --atomic and a 10-minute timeout; on a slow link a first pull can exceed it and roll the
// release back, so the pulls happen here, with their own timeout and retries.
func (d Deployer) Preload(ctx context.Context) error {
	if d.cfg.Env != "local" {
		return nil
	}
	rendered, err := d.run.Output(ctx, "helmfile", "--file", filepath.Join(d.cfg.k8sDir(), "helmfile.yaml.gotmpl"),
		"-e", d.cfg.Env, "--kube-context", d.cfg.Context(), "template", "--skip-deps")
	if err != nil {
		return err
	}
	present, err := d.run.Output(ctx, "minikube", "-p", d.cfg.Profile, "ssh", "--", "docker", "images", "--format", "{{.Repository}}:{{.Tag}}")
	if err != nil {
		return err
	}
	todo := missing(ImagesFromManifests(rendered), strings.Fields(present))
	d.log("%d image(s) to pull", len(todo))
	for i, img := range todo {
		start := time.Now()
		pull := func() error {
			pctx, cancel := context.WithTimeout(ctx, 30*time.Minute)
			defer cancel()
			return d.run.Run(pctx, "minikube", "-p", d.cfg.Profile, "ssh", "--", "docker", "pull", "-q", img)
		}
		if err := retry(ctx, 3, 10*time.Second, pull); err != nil {
			return fmt.Errorf("pull %s: %w", img, err)
		}
		d.log("[%d/%d] %s (%s)", i+1, len(todo), img, time.Since(start).Round(time.Second))
	}
	return nil
}

// Secrets creates the namespace and the secrets the charts reference. Locally the model comes from
// a PVC, so the MLflow / AWS values are placeholders the pods only need to start.
func (d Deployer) Secrets(ctx context.Context) error {
	if d.cfg.Env != "local" {
		d.log("env %s: secrets come from Terraform (kubernetes_secret.*), skipping", d.cfg.Env)
		return nil
	}
	if _, err := d.run.Output(ctx, "kubectl", "--context", d.cfg.Context(), "get", "namespace", ns); err != nil {
		if err := d.kubectl(ctx, "create", "namespace", ns); err != nil {
			return err
		}
	}
	secrets := map[string][]string{
		"mlflow-secret":   {"MLFLOW_TRACKING_URI=http://mlflow." + ns + ".svc.cluster.local:5000", "MLFLOW_S3_ENDPOINT_URL=http://unused:9000"},
		"aws-credentials": {"AWS_ACCESS_KEY_ID=unused", "AWS_SECRET_ACCESS_KEY=unused"},
	}
	for _, name := range []string{"mlflow-secret", "aws-credentials"} {
		if _, err := d.run.Output(ctx, "kubectl", "--context", d.cfg.Context(), "-n", ns, "get", "secret", name); err == nil {
			continue
		}
		args := []string{"-n", ns, "create", "secret", "generic", name}
		for _, kv := range secrets[name] {
			args = append(args, "--from-literal="+kv)
		}
		if err := d.kubectl(ctx, args...); err != nil {
			return err
		}
	}
	return nil
}

// Model exports the MLflow pyfunc from the current folds and copies it to the PVC the local
// InferenceService mounts (pvc://hallucination-model-store/model, values/model-local.yaml).
func (d Deployer) Model(ctx context.Context) error {
	if d.cfg.Env != "local" {
		d.log("env %s: the model comes from the MLflow registry (storageUri), skipping", d.cfg.Env)
		return nil
	}
	out := filepath.Join(d.cfg.Root, "artifacts", "local", "serving-model")
	store := filepath.Join(d.cfg.k8sDir(), "local", "model-store.yaml")
	if err := d.run.Run(ctx, d.cfg.Python, filepath.Join(d.cfg.Root, "machine-learning", "scripts", "export_serving_model.py"), out); err != nil {
		return err
	}
	for _, args := range [][]string{
		{"apply", "-f", store},
		{"-n", ns, "wait", "pod/model-store-loader", "--for=condition=Ready", "--timeout=300s"},
		{"-n", ns, "exec", "model-store-loader", "--", "rm", "-rf", "/store/model"},
		{"-n", ns, "cp", out, "model-store-loader:/store/model"},
		{"-n", ns, "delete", "pod", "model-store-loader", "--wait"},
	} {
		if err := d.kubectl(ctx, args...); err != nil {
			return err
		}
	}
	return nil
}

// adoptable lists objects that earlier tooling (kubectl, the old bash script) may have created and
// that a helmfile release now owns. Helm refuses to manage objects without its ownership metadata.
var adoptable = []struct{ kind, name, namespace, release, releaseNS string }{
	{"namespace", ns, "", "namespaces", "default"},
	{"namespace", "monitoring", "", "namespaces", "default"},
	{"clusterservingruntime", "mlflow-runtime", "", "mlflow-runtime", ns},
}

// Adopt adds Helm's ownership label and annotations to those objects. Metadata only, nothing is
// deleted or recreated.
func (d Deployer) Adopt(ctx context.Context) error {
	for _, o := range adoptable {
		got, err := d.run.Output(ctx, "kubectl", "--context", d.cfg.Context(), "get", o.kind, o.name,
			"-o", "jsonpath={.metadata.annotations.meta\\.helm\\.sh/release-name}")
		if err != nil {
			continue // not there: the release creates it
		}
		if strings.TrimSpace(got) == o.release {
			continue
		}
		if err := d.kubectl(ctx, "label", o.kind, o.name, "app.kubernetes.io/managed-by=Helm", "--overwrite"); err != nil {
			return err
		}
		if err := d.kubectl(ctx, "annotate", o.kind, o.name, "meta.helm.sh/release-name="+o.release,
			"meta.helm.sh/release-namespace="+o.releaseNS, "--overwrite"); err != nil {
			return err
		}
		d.log("adopted %s/%s into release %s", o.kind, o.name, o.release)
	}
	return nil
}

// Sync runs the helmfile for the environment. selector narrows it, e.g. "tier=app".
func (d Deployer) Sync(ctx context.Context, selector string) error {
	args := []string{"--file", filepath.Join(d.cfg.k8sDir(), "helmfile.yaml.gotmpl"), "-e", d.cfg.Env, "--kube-context", d.cfg.Context()}
	if selector != "" {
		args = append(args, "-l", selector)
	}
	return d.run.Run(ctx, "helmfile", append(args, "sync")...)
}

// Status prints nodes, pods and the InferenceService.
func (d Deployer) Status(ctx context.Context) error {
	for _, args := range [][]string{
		{"get", "nodes", "-o", "wide"},
		{"get", "pods", "-A"},
		{"-n", ns, "get", "inferenceservice"},
	} {
		if err := d.kubectl(ctx, args...); err != nil {
			return err
		}
	}
	return nil
}

// Step names in the order `all` runs them.
var stepOrder = []string{"up", "addons", "images", "preload", "secrets", "model", "adopt", "sync", "status"}

func (d Deployer) Step(ctx context.Context, name, selector string) error {
	switch name {
	case "up":
		return d.Up(ctx)
	case "addons":
		return d.Addons(ctx)
	case "images":
		return d.Images(ctx)
	case "preload":
		return d.Preload(ctx)
	case "secrets":
		return d.Secrets(ctx)
	case "model":
		return d.Model(ctx)
	case "adopt":
		return d.Adopt(ctx)
	case "sync":
		return d.Sync(ctx, selector)
	case "status":
		return d.Status(ctx)
	case "all":
		for _, s := range stepOrder {
			d.log("== %s", s)
			if err := d.Step(ctx, s, selector); err != nil {
				return fmt.Errorf("step %s: %w", s, err)
			}
		}
		return nil
	}
	return fmt.Errorf("unknown command %q", name)
}
