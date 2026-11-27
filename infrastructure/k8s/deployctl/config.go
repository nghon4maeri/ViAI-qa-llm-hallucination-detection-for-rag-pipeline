package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Pinned versions: the same ones local/deploy-minikube.sh installed and the docs describe.
const (
	certManagerVersion = "v1.16.2"
	kserveVersion      = "v0.16.0"
	k8sVersion         = "v1.34.0"
)

// Config is shared by every step. It never reads or changes kubectl's default context: every
// kubectl / helm / helmfile call gets the context explicitly.
type Config struct {
	Profile    string // minikube profile == kube context of the local cluster
	Env        string // helmfile environment: local | prod
	Root       string // repository root
	AllowCloud bool   // required for any context that looks like a cloud cluster
	Memory     string
	CPUs       string
	Python     string // interpreter for machine-learning/scripts (exports the serving model)
}

func (c Config) k8sDir() string { return filepath.Join(c.Root, "infrastructure", "k8s") }

// Context is the kube context every command targets.
func (c Config) Context() string { return c.Profile }

var errCloud = errors.New("refusing a cloud kube context: deployctl targets local clusters; pass --allow-cloud with --env prod to deploy to GKE")

// checkContext enforces "no cloud deploys while GKE has no budget" in code, not in a README.
func (c Config) checkContext() error {
	ctx := c.Context()
	cloud := strings.HasPrefix(ctx, "gke_") || strings.HasPrefix(ctx, "arn:aws:eks") || strings.Contains(ctx, "aks")
	switch {
	case cloud && !c.AllowCloud:
		return errCloud
	case cloud && c.Env != "prod":
		return fmt.Errorf("cloud context %q needs --env prod", ctx)
	case !cloud && c.Env == "prod" && !c.AllowCloud:
		return fmt.Errorf("--env prod is for GKE; use --env local for %q", ctx)
	}
	return nil
}

// findRoot walks up from dir to the directory holding dvc.yaml (the repository root).
func findRoot(dir string) (string, error) {
	for d := dir; ; d = filepath.Dir(d) {
		if _, err := os.Stat(filepath.Join(d, "dvc.yaml")); err == nil {
			return d, nil
		}
		if filepath.Dir(d) == d {
			return "", errors.New("repository root (dvc.yaml) not found; run deployctl inside the repo")
		}
	}
}
