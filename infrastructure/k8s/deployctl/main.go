// Command deployctl drives the Kubernetes side of ViAI-QA: the local minikube cluster, its add-ons,
// local images, and the helmfile releases. Terraform, Ansible, Helm and helmfile stay the tools
// of record; deployctl runs them in the right order with explicit kube contexts.
//
//	deployctl [flags] <command>
//
// Commands: up, addons, images, preload, secrets, model, adopt, sync, status, all.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
)

const usage = `usage: deployctl [flags] <command>

commands (all runs them in this order):
  up        start the minikube profile (local only)
  addons    install cert-manager and KServe (Standard mode)
  images    build local images and load them into the cluster
  preload   pull every public image the releases need, before sync
  secrets   namespace + placeholder secrets the charts reference (local only)
  model     export the serving model and copy it to the model PVC (local only)
  adopt     give pre-existing namespaces / runtime to their helmfile releases
  sync      helmfile sync for --env (narrow with -l tier=app)
  status    nodes, pods, InferenceService
  all       everything above

flags:
`

func main() {
	cfg := Config{}
	var dryRun bool
	var selector string
	fs := flag.NewFlagSet("deployctl", flag.ExitOnError)
	fs.StringVar(&cfg.Profile, "profile", "viai-qa", "minikube profile / kube context")
	fs.StringVar(&cfg.Env, "env", "local", "helmfile environment: local | prod")
	fs.BoolVar(&cfg.AllowCloud, "allow-cloud", false, "allow a cloud kube context (GKE); needs --env prod")
	fs.StringVar(&cfg.Memory, "memory", "5g", "minikube memory")
	fs.StringVar(&cfg.CPUs, "cpus", "4", "minikube CPUs")
	fs.StringVar(&cfg.Python, "python", "python", "Python interpreter for machine-learning/scripts")
	fs.StringVar(&selector, "l", "", "helmfile selector for sync, e.g. tier=app")
	fs.BoolVar(&dryRun, "dry-run", false, "print the commands that change things instead of running them")
	fs.Usage = func() { fmt.Fprint(os.Stderr, usage); fs.PrintDefaults() }
	_ = fs.Parse(os.Args[1:])
	if fs.NArg() != 1 {
		fs.Usage()
		os.Exit(2)
	}

	wd, _ := os.Getwd()
	root, err := findRoot(wd)
	if err != nil {
		fail(err)
	}
	cfg.Root = root
	if err := cfg.checkContext(); err != nil {
		fail(err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	d := Deployer{cfg: cfg, run: newExecRunner(root, dryRun), log: func(f string, a ...any) {
		fmt.Printf("[deployctl] "+f+"\n", a...)
	}}
	if err := d.Step(ctx, strings.TrimSpace(fs.Arg(0)), selector); err != nil {
		fail(err)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "deployctl:", err)
	os.Exit(1)
}
