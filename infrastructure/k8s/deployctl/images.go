package main

import (
	"regexp"
	"sort"
	"strings"
)

// LocalImage is built from the repo and loaded into the cluster; it is never pulled.
type LocalImage struct {
	Tag        string // name:tag used by the local values files
	Dockerfile string // relative to the repo root
	Context    string // build context, relative to the repo root
}

// localImages are the images values/*-local.yaml reference.
var localImages = []LocalImage{
	{"hallucination-predictor:local", "infrastructure/docker/Dockerfile.predictor", "infrastructure/docker"},
	{"hallucination-backend-lite:local", "infrastructure/docker/Dockerfile.backend-lite", "."},
	{"mlflow:local", "infrastructure/mlflow/Dockerfile", "infrastructure/mlflow"},
	{"evidently-drift:local", "infrastructure/observability/evidently/Dockerfile", "infrastructure/observability/evidently"},
}

// hostImages are public images that are cheaper to copy from the host's docker than to pull again.
var hostImages = []string{"postgres:17"}

var (
	reImage    = regexp.MustCompile(`(?m)^\s*-?\s*image:\s*["']?([^"'\s]+)["']?\s*$`)
	reKind     = regexp.MustCompile(`(?m)^kind:\s*(\S+)`)
	reVersion  = regexp.MustCompile(`(?m)^\s{2}version:\s*["']?([^"'\s]+)`)
	reReloader = regexp.MustCompile(`--prometheus-config-reloader=(\S+)`)
	reTestHook = regexp.MustCompile(`helm\.sh/hook["']?:\s*["']?test`)
)

// ImagesFromManifests lists the container images a rendered `helmfile template` will run:
// container/initContainer images, the Prometheus CR (the operator starts it, so its image only
// appears as `version`), and the config reloader passed to the operator as a flag. Helm test hooks
// are skipped because `helmfile sync` does not run them.
func ImagesFromManifests(rendered string) []string {
	seen := map[string]bool{}
	for _, doc := range strings.Split(rendered, "\n---") {
		if reTestHook.MatchString(doc) {
			continue
		}
		for _, m := range reImage.FindAllStringSubmatch(doc, -1) {
			seen[m[1]] = true
		}
		if k := reKind.FindStringSubmatch(doc); k != nil && k[1] == "Prometheus" {
			if v := reVersion.FindStringSubmatch(doc); v != nil && !reImage.MatchString(doc) {
				seen["quay.io/prometheus/prometheus:"+v[1]] = true
			}
		}
		for _, m := range reReloader.FindAllStringSubmatch(doc, -1) {
			seen[m[1]] = true
		}
	}
	for _, l := range localImages {
		delete(seen, l.Tag)
	}
	out := make([]string, 0, len(seen))
	for img := range seen {
		if strings.Contains(img, "{{") || strings.HasPrefix(img, "map[") {
			continue // unrendered template or a values mistake; the chart lint catches those
		}
		out = append(out, img)
	}
	sort.Strings(out)
	return out
}

// normalizeRef makes "grafana/loki:2.6.1" and "docker.io/grafana/loki:2.6.1" compare equal, so an
// image already on the node is not pulled again.
func normalizeRef(ref string) string {
	ref = strings.SplitN(ref, "@", 2)[0]
	for _, p := range []string{"docker.io/library/", "docker.io/"} {
		ref = strings.TrimPrefix(ref, p)
	}
	if !strings.Contains(ref, ":") {
		ref += ":latest"
	}
	return ref
}

// missing returns the wanted images not present on the node.
func missing(wanted []string, present []string) []string {
	have := map[string]bool{}
	for _, p := range present {
		have[normalizeRef(p)] = true
	}
	var out []string
	for _, w := range wanted {
		if !have[normalizeRef(w)] {
			out = append(out, w)
		}
	}
	return out
}
