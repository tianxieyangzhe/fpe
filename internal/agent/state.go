package agent

import (
	"time"

	"github.com/yangshuai/fpe/internal/db"
	"github.com/yangshuai/fpe/internal/walker"
)

// --- MCP input types ---

type DiagnoseInput struct {
	Query   string          `json:"query"`
	Packet  *PacketInput    `json:"packet,omitempty"`
	Context *DiagnoseContext `json:"context,omitempty"`
	Debug   bool            `json:"debug"`
}

type PacketInput struct {
	SrcIP     string `json:"src_ip,omitempty"`
	DstIP     string `json:"dst_ip,omitempty"`
	Proto     string `json:"proto,omitempty"`
	SrcPort   *int   `json:"src_port,omitempty"`
	DstPort   *int   `json:"dst_port,omitempty"`
	Namespace string `json:"namespace,omitempty"`
}

type DiagnoseContext struct {
	DB            string   `json:"db,omitempty"`
	SourceRoot    string   `json:"source_root,omitempty"`
	Focus         []string `json:"focus,omitempty"`
	MaxCodeChunks int      `json:"max_code_chunks,omitempty"`
}

// --- Pipeline state ---

type AgentState struct {
	Input          DiagnoseInput
	Normalized     NormalizedRequest
	Snapshot       SnapshotSummary
	PathResult     *walker.WalkResult
	Tokens         []SearchToken
	CodeChunks     []CodeChunk
	Dossier        InvestigationDossier
	Analysis       string
	ReportMarkdown string
	DebugInfo      DebugInfo
	Warnings       []string
}

// --- Normalized request ---

type NormalizedRequest struct {
	Query         string
	Packet        *WalkerTuple
	SourceRoot    string
	Focus         []string
	MaxCodeChunks int
	Debug         bool
	Capabilities  RequestCapabilities
}

type WalkerTuple struct {
	Resolved bool
	Tuple    walker.PacketTuple
}

type RequestCapabilities struct {
	CanDoPath       bool
	CanSearchSource bool
	MissingFields   []string
}

// --- Snapshot summary ---

type SnapshotSummary struct {
	Interfaces []db.Interface `json:"interfaces"`
	Routes     []db.Route     `json:"routes"`
	Neighbors  []db.Neighbor  `json:"neighbors"`
	OvsBridges []db.OvsBridge `json:"ovs_bridges"`
	OvsFlows   []db.OvsFlow   `json:"ovs_flows"`
	FrrInfo    []db.FrrInfo   `json:"frr_info"`
	Warnings   []string       `json:"warnings"`
}

// --- Source search types ---

type SearchToken struct {
	Value      string `json:"value"`
	Type       string `json:"type"`
	Source     string `json:"source"`
	Weight     int    `json:"weight"`
	ExactMatch bool   `json:"exact_match"`
}

// Token weight constants
const (
	TokenWeightOVSCookie  = 100
	TokenWeightVRF        = 90
	TokenWeightVNI        = 90
	TokenWeightPrefix     = 80
	TokenWeightInterface  = 70
	TokenWeightOVSTable   = 65
	TokenWeightOVSGroup   = 65
	TokenWeightIP         = 60
	TokenWeightFRRKeyword = 50
	TokenWeightKeyword    = 20
)

// CodeChunk represents a complete code unit from source search.
type CodeChunk struct {
	FilePath      string        `json:"file_path"`
	PackageName   string        `json:"package_name"`
	Kind          string        `json:"kind"`
	Name          string        `json:"name"`
	Receiver      string        `json:"receiver"`
	StartLine     int           `json:"start_line"`
	EndLine       int           `json:"end_line"`
	DocComment    string        `json:"doc_comment"`
	Lines         string        `json:"lines"`
	MatchedTokens []SearchToken `json:"matched_tokens"`
	Callees       []string      `json:"callees"`
	Score         int           `json:"score"`
}

// --- Dossier ---

type InvestigationDossier struct {
	Query          string            `json:"query"`
	Snapshot       SnapshotSummary   `json:"snapshot"`
	PathResult     *walker.WalkResult `json:"path_result,omitempty"`
	CodeChunks     []CodeChunk       `json:"code_chunks,omitempty"`
	Evidence       []EvidenceItem    `json:"evidence"`
	UncertainItems []string          `json:"uncertain_items"`
	HasSourceCode  bool              `json:"has_source_code"`
}

type EvidenceItem struct {
	Category string `json:"category"`
	Summary  string `json:"summary"`
	Detail   string `json:"detail"`
}

// --- Debug ---

type DebugInfo struct {
	NormalizedInput  any            `json:"normalized_input"`
	Tokens           []SearchToken  `json:"tokens"`
	CodeChunkSummary []ChunkSummary `json:"code_chunk_summary"`
	DossierSummary   any            `json:"dossier_summary"`
	Warnings         []string       `json:"warnings"`
}

type ChunkSummary struct {
	File   string `json:"file"`
	Symbol string `json:"symbol"`
	Lines  string `json:"lines"`
	Score  int    `json:"score"`
}

// --- Dependencies ---

type Dependencies struct {
	DB   *db.DB
	Now  func() time.Time
}

// PacketInputToTuple converts MCP PacketInput to walker.PacketTuple.
func PacketInputToTuple(in *PacketInput) walker.PacketTuple {
	if in == nil {
		return walker.PacketTuple{}
	}
	pkt := walker.PacketTuple{
		SrcIP:     in.SrcIP,
		DstIP:     in.DstIP,
		Proto:     in.Proto,
		Namespace: in.Namespace,
	}
	if in.DstPort != nil {
		p := *in.DstPort
		pkt.DstPort = &p
	}
	if in.SrcPort != nil {
		p := *in.SrcPort
		pkt.SrcPort = &p
	}
	return pkt
}
