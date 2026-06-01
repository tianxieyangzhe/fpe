package mcp

import (
	"context"
	"fmt"
	"net/http"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/logs"
)

func NewServer(d *db.DB) *mcp.Server {
	s := mcp.NewServer(&mcp.Implementation{Name: "fpe", Version: "1.0.0"}, nil)

	addGetInterfaces(s, d)
	addGetRoutes(s, d)
	addGetNeighbors(s, d)
	addGetOvsBridges(s, d)
	addGetOvsFlows(s, d)
	addGetOvsGroups(s, d)
	addGetOvsFDB(s, d)
	addGetOvsTnlARP(s, d)
	addResolvePacket(s, d)
	addGetPathSegments(s, d)
	addGetFrrInfo(s, d)

	return s
}

// Serve starts the MCP server on the given transport.
// Supported transports: stdio, sse, streamable-http.
func Serve(d *db.DB, transport, addr string) error {
	s := NewServer(d)
	switch transport {
	case "stdio":
		return s.Run(context.Background(), &mcp.StdioTransport{})
	case "sse":
		h := mcp.NewSSEHandler(func(r *http.Request) *mcp.Server { return s }, nil)
		logs.Infof("MCP SSE server listening: %s", addr)
		return http.ListenAndServe(addr, h)
	case "mcp":
		h := mcp.NewStreamableHTTPHandler(func(r *http.Request) *mcp.Server { return s }, nil)
		logs.Infof("MCP Streamable HTTP server listening: %s", addr)
		return http.ListenAndServe(addr, h)
	default:
		return fmt.Errorf("unknown transport: %s", transport)
	}
}
