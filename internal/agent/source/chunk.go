package source

import (
	"sort"
	"strings"

	"github.com/yangshuai/fpe/internal/agent"
)

// RawMatch is the parsed output of `rg --json`.
type RawMatch struct {
	Token    agent.SearchToken
	FilePath string
	Line     int
	LineText string
	Context  []string
}

// ScoreCodeChunks scores, sorts, and truncates code chunks for dossier injection.
func ScoreCodeChunks(chunks []agent.CodeChunk, focus []string, maxChunks int, maxLinesPerChunk int) []agent.CodeChunk {
	for i := range chunks {
		c := &chunks[i]

		tokenWeightSum := 0
		for _, t := range c.MatchedTokens {
			tokenWeightSum += t.Weight
		}
		c.Score = tokenWeightSum

		if len(c.MatchedTokens) > 1 {
			c.Score += 10 * len(c.MatchedTokens)
		}

		nameLower := strings.ToLower(c.Name)
		pathLower := strings.ToLower(c.FilePath)
		commentLower := strings.ToLower(c.DocComment)
		for _, f := range focus {
			fl := strings.ToLower(f)
			if strings.Contains(nameLower, fl) {
				c.Score += 30
			}
			if strings.Contains(pathLower, fl) {
				c.Score += 20
			}
			if strings.Contains(commentLower, fl) {
				c.Score += 10
			}
		}

		lineCount := c.EndLine - c.StartLine + 1
		if lineCount > 300 {
			c.Score -= 40
		}
	}

	sort.Slice(chunks, func(i, j int) bool {
		return chunks[i].Score > chunks[j].Score
	})

	if len(chunks) > maxChunks {
		chunks = chunks[:maxChunks]
	}

	for i := range chunks {
		lines := strings.Split(chunks[i].Lines, "\n")
		if len(lines) > maxLinesPerChunk {
			chunks[i].Lines = strings.Join(lines[:maxLinesPerChunk], "\n") + "\n..."
		}
	}

	return chunks
}

// TruncateTokens limits tokens to a maximum count, keeping highest weight first.
func TruncateTokens(tokens []agent.SearchToken, max int) []agent.SearchToken {
	if len(tokens) <= max {
		return tokens
	}
	return tokens[:max]
}
