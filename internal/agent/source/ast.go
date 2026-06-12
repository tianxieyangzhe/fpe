package source

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"strings"

	"github.com/yangshuai/fpe/internal/agent"
)

// ASTExpander extracts complete code chunks from Go source files given hit locations.
type ASTExpander struct{}

// ExpandToChunk reads the given Go file, parses its AST, finds the
// FuncDecl/TypeSpec/GenDecl containing line, and returns a CodeChunk.
func (e *ASTExpander) ExpandToChunk(filePath string, line int, matchedTokens []agent.SearchToken) (*agent.CodeChunk, error) {
	src, err := os.ReadFile(filePath)
	if err != nil {
		return nil, err
	}

	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, filePath, src, parser.ParseComments)
	if err != nil {
		// Fallback: return a window around the hit line
		return fallbackChunk(filePath, line, src, matchedTokens), nil
	}

	// Try FuncDecl first
	for _, decl := range file.Decls {
		if fd, ok := decl.(*ast.FuncDecl); ok {
			start := fset.Position(fd.Pos()).Line
			end := fset.Position(fd.End()).Line
			if start <= line && line <= end {
				return funcChunk(filePath, fset, fd, src, start, end, matchedTokens), nil
			}
		}
	}

	// Try TypeSpec
	for _, decl := range file.Decls {
		if gd, ok := decl.(*ast.GenDecl); ok && gd.Tok == token.TYPE {
			for _, spec := range gd.Specs {
				if ts, ok := spec.(*ast.TypeSpec); ok {
					start := fset.Position(ts.Pos()).Line
					end := fset.Position(ts.End()).Line
					if start <= line && line <= end {
						return typeChunk(filePath, fset, ts, gd, src, start, end, matchedTokens), nil
					}
				}
			}
		}
	}

	// Try GenDecl (const/var)
	for _, decl := range file.Decls {
		if gd, ok := decl.(*ast.GenDecl); ok && (gd.Tok == token.CONST || gd.Tok == token.VAR) {
			start := fset.Position(gd.Pos()).Line
			end := fset.Position(gd.End()).Line
			if start <= line && line <= end {
				kind := "const"
				if gd.Tok == token.VAR {
					kind = "var"
				}
				return genChunk(filePath, kind, src, start, end, matchedTokens), nil
			}
		}
	}

	return fallbackChunk(filePath, line, src, matchedTokens), nil
}

func funcChunk(filePath string, fset *token.FileSet, fd *ast.FuncDecl, src []byte, start, end int, matchedTokens []agent.SearchToken) *agent.CodeChunk {
	lines := extractLines(src, start, end)
	name := fd.Name.Name
	if fd.Recv != nil && len(fd.Recv.List) > 0 {
		// Don't set receiver here to keep it simple; we extract method via name context
	}

	doc := ""
	if fd.Doc != nil {
		doc = fd.Doc.Text()
	}

	var callees []string
	if fd.Body != nil {
		callees = extractCallees(fd.Body)
	}

	return &agent.CodeChunk{
		FilePath:      filePath,
		PackageName:   "",
		Kind:          "function",
		Name:          name,
		StartLine:     start,
		EndLine:       end,
		DocComment:    strings.TrimSpace(doc),
		Lines:         lines,
		MatchedTokens: matchedTokens,
		Callees:       callees,
	}
}

func typeChunk(filePath string, fset *token.FileSet, ts *ast.TypeSpec, gd *ast.GenDecl, src []byte, start, end int, matchedTokens []agent.SearchToken) *agent.CodeChunk {
	lines := extractLines(src, start, end)
	doc := ""
	if gd.Doc != nil {
		doc = gd.Doc.Text()
	}
	return &agent.CodeChunk{
		FilePath:      filePath,
		Kind:          "type",
		Name:          ts.Name.Name,
		StartLine:     start,
		EndLine:       end,
		DocComment:    strings.TrimSpace(doc),
		Lines:         lines,
		MatchedTokens: matchedTokens,
	}
}

func genChunk(filePath, kind string, src []byte, start, end int, matchedTokens []agent.SearchToken) *agent.CodeChunk {
	lines := extractLines(src, start, end)
	return &agent.CodeChunk{
		FilePath:      filePath,
		Kind:          kind,
		StartLine:     start,
		EndLine:       end,
		Lines:         lines,
		MatchedTokens: matchedTokens,
	}
}

func fallbackChunk(filePath string, line int, src []byte, matchedTokens []agent.SearchToken) *agent.CodeChunk {
	allLines := strings.Split(string(src), "\n")
	start := line - 25
	if start < 0 {
		start = 0
	}
	end := line + 25
	if end > len(allLines) {
		end = len(allLines)
	}
	return &agent.CodeChunk{
		FilePath:      filePath,
		Kind:          "file",
		StartLine:     start + 1,
		EndLine:       end,
		Lines:         strings.Join(allLines[start:end], "\n"),
		MatchedTokens: matchedTokens,
	}
}

func extractLines(src []byte, start, end int) string {
	allLines := strings.Split(string(src), "\n")
	if start < 1 {
		start = 1
	}
	if end > len(allLines) {
		end = len(allLines)
	}
	return strings.Join(allLines[start-1:end], "\n")
}

func extractCallees(body *ast.BlockStmt) []string {
	var callees []string
	ast.Inspect(body, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		switch fun := call.Fun.(type) {
		case *ast.Ident:
			callees = append(callees, fun.Name)
		case *ast.SelectorExpr:
			if x, ok := fun.X.(*ast.Ident); ok {
				callees = append(callees, x.Name+"."+fun.Sel.Name)
			}
		}
		return true
	})
	return callees
}
