package main

import (
	"os"

	"github.com/spf13/cobra"
	"github.com/yangshuai/fpe/cmd/collect"
	"github.com/yangshuai/fpe/cmd/serve"
	"github.com/yangshuai/fpe/internal/logs"
)

func main() {
	logs.Init(true)

	root := &cobra.Command{Use: "fpe"}
	root.AddCommand(collect.NewCommand(), serve.NewCommand())
	if err := root.Execute(); err != nil {
		logs.Errorf("command failed: %v", err)
		os.Exit(1)
	}
}
