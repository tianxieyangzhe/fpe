package serve

import (
	"github.com/spf13/cobra"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/mcp"
)

func NewCommand() *cobra.Command {
	var dbPath, transport, addr string

	cmd := &cobra.Command{
		Use:   "serve",
		Short: "Start MCP server backed by knowledge base",
		RunE: func(cmd *cobra.Command, args []string) error {
			d, err := db.Open(dbPath)
			if err != nil {
				return err
			}
			defer d.Close()
			return mcp.Serve(d, transport, addr)
		},
	}

	cmd.Flags().StringVar(&dbPath, "db", "", "path to SQLite db")
	cmd.Flags().StringVar(&transport, "transport", "stdio", "stdio, sse, or streamable-http")
	cmd.Flags().StringVar(&addr, "addr", ":8080", "listen address for SSE/streamable-http mode")
	cmd.MarkFlagRequired("db")
	return cmd
}
