package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

// Runner executes external tools. The real one shells out; tests use a recorder, so the command
// plan of every step can be checked without a cluster.
type Runner interface {
	// Run streams output and fails on a non-zero exit.
	Run(ctx context.Context, name string, args ...string) error
	// Output returns stdout; stderr is kept for the error message.
	Output(ctx context.Context, name string, args ...string) (string, error)
}

type execRunner struct {
	dir    string
	dryRun bool
	out    io.Writer
}

func (r execRunner) command(ctx context.Context, name string, args []string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = r.dir
	// Never inherit the terminal's stdin: `minikube ssh` and friends read it and swallow input
	// meant for the caller (this broke the bash pre-pull loop after the first image).
	cmd.Stdin = nil
	return cmd
}

func (r execRunner) Run(ctx context.Context, name string, args ...string) error {
	fmt.Fprintf(r.out, "+ %s %s\n", name, strings.Join(args, " "))
	if r.dryRun {
		return nil
	}
	cmd := r.command(ctx, name, args)
	cmd.Stdout, cmd.Stderr = r.out, r.out
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s %s: %w", name, strings.Join(args, " "), err)
	}
	return nil
}

func (r execRunner) Output(ctx context.Context, name string, args ...string) (string, error) {
	cmd := r.command(ctx, name, args)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return stdout.String(), fmt.Errorf("%s %s: %w: %s", name, strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return stdout.String(), nil
}

// retry runs fn up to attempts times, waiting between tries (image pulls on a slow link fail now and then).
func retry(ctx context.Context, attempts int, wait time.Duration, fn func() error) error {
	var err error
	for i := 1; i <= attempts; i++ {
		if err = fn(); err == nil {
			return nil
		}
		if i < attempts {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(wait):
			}
		}
	}
	return err
}

func newExecRunner(dir string, dryRun bool) Runner {
	return execRunner{dir: dir, dryRun: dryRun, out: os.Stdout}
}
