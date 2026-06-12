package source

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/yangshuai/fpe/internal/agent"
	"github.com/yangshuai/fpe/internal/logs"
)

var ErrRgUnavailable = errors.New("rg not available")

// RgSearcher handles rg-based code search.
type RgSearcher struct {
	SourceRoot string
	Available  bool
}

// NewRgSearcher checks if rg is available on PATH.
func NewRgSearcher(sourceRoot string) *RgSearcher {
	_, err := exec.LookPath("rg")
	return &RgSearcher{
		SourceRoot: sourceRoot,
		Available:  err == nil,
	}
}

// Search runs rg for each token and returns deduplicated matches.
func (s *RgSearcher) Search(tokens []agent.SearchToken) ([]RawMatch, error) {
	if !s.Available {
		return nil, ErrRgUnavailable
	}

	seen := make(map[string]map[int]bool)
	var matches []RawMatch

	for _, token := range tokens {
		if token.Value == "" {
			continue
		}
		results, err := s.searchToken(token)
		if err != nil {
			logs.Debugf("rg search token=%q: %v", token.Value, err)
			continue
		}
		for _, m := range results {
			if seenFile, ok := seen[m.FilePath]; ok && seenFile[m.Line] {
				continue
			}
			if seen[m.FilePath] == nil {
				seen[m.FilePath] = make(map[int]bool)
			}
			seen[m.FilePath][m.Line] = true
			m.Token = token
			matches = append(matches, m)
		}
	}
	return matches, nil
}

func (s *RgSearcher) searchToken(token agent.SearchToken) ([]RawMatch, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	args := []string{
		"--json",
		"--fixed-strings",
		"--line-number",
		"--context", "2",
		"--glob", "*.go",
		"--glob", "!vendor/**",
		"--glob", "!.git/**",
		"--glob", "!*_test.go",
		token.Value,
		s.SourceRoot,
	}

	cmd := exec.CommandContext(ctx, "rg", args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}

	var matches []RawMatch
	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		line := scanner.Text()
		var entry struct {
			Type string `json:"type"`
			Data struct {
				Path struct {
					Text string `json:"text"`
				} `json:"path"`
				LineNumber int `json:"line_number"`
				Lines struct {
					Text string `json:"text"`
				} `json:"lines"`
			} `json:"data"`
		}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		if entry.Type != "match" {
			continue
		}
		match := RawMatch{
			FilePath: entry.Data.Path.Text,
			Line:     entry.Data.LineNumber,
			LineText: entry.Data.Lines.Text,
		}
		matches = append(matches, match)
	}

	_ = cmd.Wait() // exit code 1 means no matches, not an error
	return matches, nil
}

// FileScanFallback walks sourceRoot for *.go files and does string matching.
// Used when rg is unavailable.
func FileScanFallback(sourceRoot string, tokens []agent.SearchToken) ([]RawMatch, error) {
	var matches []RawMatch
	seen := make(map[string]map[int]bool)

	for _, token := range tokens {
		if token.Value == "" {
			continue
		}
		results, err := scanFilesForToken(sourceRoot, token)
		if err != nil {
			logs.Debugf("file scan token=%q: %v", token.Value, err)
			continue
		}
		for _, m := range results {
			if seenFile, ok := seen[m.FilePath]; ok && seenFile[m.Line] {
				continue
			}
			if seen[m.FilePath] == nil {
				seen[m.FilePath] = make(map[int]bool)
			}
			seen[m.FilePath][m.Line] = true
			matches = append(matches, m)
		}
	}
	return matches, nil
}

func scanFilesForToken(root string, token agent.SearchToken) ([]RawMatch, error) {
	var matches []RawMatch
	err := filepathWalk(root, func(path string, info os.FileInfo) error {
		if !strings.HasSuffix(path, ".go") {
			return nil
		}
		if strings.Contains(path, "/vendor/") || strings.Contains(path, "/.git/") {
			return nil
		}
		if strings.HasSuffix(path, "_test.go") {
			return nil
		}
		f, err := os.Open(path)
		if err != nil {
			return nil
		}
		defer f.Close()
		scanner := bufio.NewScanner(f)
		lineNum := 0
		for scanner.Scan() {
			lineNum++
			if strings.Contains(scanner.Text(), token.Value) {
				relPath := path
				if strings.HasPrefix(path, root) {
					relPath = strings.TrimPrefix(path, root)
					relPath = strings.TrimPrefix(relPath, "/")
				}
				matches = append(matches, RawMatch{
					FilePath: relPath,
					Line:     lineNum,
					LineText: scanner.Text(),
				})
				if len(matches) > 200 {
					return fmt.Errorf("too many matches")
				}
			}
		}
		return nil
	})
	return matches, err
}

func filepathWalk(root string, fn func(string, os.FileInfo) error) error {
	return filepathWalkDir(root, root, fn)
}

func filepathWalkDir(root, dir string, fn func(string, os.FileInfo) error) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	for _, entry := range entries {
		path := dir + "/" + entry.Name()
		info, _ := entry.Info()
		if entry.IsDir() {
			name := entry.Name()
			if name == "vendor" || name == ".git" || name == "testdata" {
				continue
			}
			if err := filepathWalkDir(root, path, fn); err != nil {
				return err
			}
			continue
		}
		if err := fn(path, info); err != nil {
			return err
		}
	}
	return nil
}
