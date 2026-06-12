package remote

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/yangshuai/fpe/internal/logs"
)

func jsonArray(cmd, out string, target interface{}) error {
	out = strings.TrimSpace(out)
	if out == "" {
		logs.Warnf("json parse failed: empty output, cmd=%q", cmd)
		return fmt.Errorf("empty output")
	}

	if err := json.Unmarshal([]byte(out), target); err == nil {
		return nil
	}

	start := strings.Index(out, "[")
	end := strings.LastIndex(out, "]")
	if start == -1 || end == -1 || end <= start {
		logs.Warnf("json parse failed, cmd=%q", cmd)
		return fmt.Errorf("no JSON array found in output")
	}

	segment := out[start : end+1]
	if err := json.Unmarshal([]byte(segment), target); err != nil {
		logs.Warnf("json parse failed, cmd=%q", cmd)
		return fmt.Errorf("parse extracted JSON array: %w", err)
	}

	logs.Debugf("extracted JSON from mixed output (orig=%d bytes, extracted=%d bytes)", len(out), len(segment))
	return nil
}
