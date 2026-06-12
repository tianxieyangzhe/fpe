package nodes

import (
	"context"
	"time"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/agent/source"
	"github.com/yangshuai/fpe/internal/logs"
)

func SearchSource(deps agent.Dependencies) func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
	return func(ctx context.Context, state agent.AgentState) (agent.AgentState, error) {
		if !state.Normalized.Capabilities.CanSearchSource {
			state.Warnings = append(state.Warnings, "source_search: skipped, source_root not provided")
			return state, nil
		}

		if len(state.Tokens) == 0 {
			state.Warnings = append(state.Warnings, "source_search: no tokens to search, skipped")
			return state, nil
		}

		ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
		defer cancel()

		sourceRoot := state.Normalized.SourceRoot
		searcher := source.NewRgSearcher(sourceRoot)

		rawMatches, err := searcher.Search(state.Tokens)
		if err == source.ErrRgUnavailable {
			logs.Warnf("source_search: rg not available, falling back to file scan")
			rawMatches, err = source.FileScanFallback(sourceRoot, state.Tokens)
			if err != nil {
				state.Warnings = append(state.Warnings, "source_search: file scan failed: "+err.Error())
				return state, nil
			}
		} else if err != nil {
			state.Warnings = append(state.Warnings, "source_search: rg search failed: "+err.Error())
			return state, nil
		}

		if len(rawMatches) == 0 {
			state.Warnings = append(state.Warnings, "source_search: no source code matches found")
			return state, nil
		}

		logs.Debugf("source_search: %d raw matches", len(rawMatches))

		expander := &source.ASTExpander{}
		var chunks []agent.CodeChunk
		chunkSeen := make(map[string]map[int]bool)

		for _, m := range rawMatches {
			path := m.FilePath
			if chunkSeen[path] != nil && chunkSeen[path][m.Line] {
				continue
			}
			if chunkSeen[path] == nil {
				chunkSeen[path] = make(map[int]bool)
			}

			chunk, err := expander.ExpandToChunk(path, m.Line, []agent.SearchToken{m.Token})
			if err != nil {
				logs.Debugf("source_search: AST expand failed for %s:%d: %v", path, m.Line, err)
				continue
			}
			if chunkSeen[path][chunk.StartLine] {
				continue
			}
			chunkSeen[path][chunk.StartLine] = true
			chunks = append(chunks, *chunk)
		}

		maxChunks := state.Normalized.MaxCodeChunks
		if maxChunks <= 0 {
			maxChunks = 12
		}
		chunks = source.ScoreCodeChunks(chunks, state.Normalized.Focus, maxChunks, 300)
		state.CodeChunks = chunks

		if state.Input.Debug {
			summaries := make([]agent.ChunkSummary, len(chunks))
			for i, c := range chunks {
				summaries[i] = agent.ChunkSummary{
					File:   c.FilePath,
					Symbol: c.Name,
					Lines:  formatLineRange(c.StartLine, c.EndLine),
					Score:  c.Score,
				}
			}
			state.DebugInfo.CodeChunkSummary = summaries
		}

		logs.Infof("source_search: %d code chunks found", len(chunks))
		return state, nil
	}
}

func formatLineRange(start, end int) string {
	if start == end {
		return itoa(start)
	}
	return itoa(start) + "-" + itoa(end)
}

func itoa(n int) string {
	if n <= 0 {
		return "0"
	}
	digits := make([]byte, 0, 10)
	for n > 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	return string(digits)
}
