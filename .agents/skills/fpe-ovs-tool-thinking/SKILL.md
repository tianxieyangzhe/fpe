---
name: fpe-ovs-tool-thinking
description: Use when analyzing network forwarding in this FPE project via MCP tools. Follow an OVS-first reasoning process, choose the right tool sequence, and turn broad collected data into path conclusions and flow graphs instead of querying tools in an ad hoc order.
---

# FPE OVS Tool Thinking

Use this skill when the task is to analyze forwarding path, explain why traffic did or did not exit as expected, investigate tunnel/BGP related forwarding behavior, or decide which FPE MCP tools to call and in what order.

## Core shift

Do not start from `rule -> route`.

Start from:

1. What is the traffic?
2. Which ingress interface receives it?
3. Does OVS take over immediately?
4. Which bridge / port / ofport / flow handles it?
5. Does OVS drop it, output it, or hand it to kernel L3?
6. Only if traffic enters kernel L3, continue with `rule -> route -> neighbor`.

Treat raw tool outputs as evidence, not as the answer. The answer should be a path conclusion.

## Hard rule: OVS analysis must drill down to specific flows

Whenever the analysis touches OVS in any way, the reasoning, evidence, and report MUST be specific down to individual flow entries (and group entries when group actions are involved). Bridge-level, port-level, or table-level observations alone are never sufficient.

This rule applies to:

- forwarding path explanation
- deviation diagnosis
- monitoring guidance
- mermaid diagrams
- markdown reports
- any conclusion that mentions an OVS bridge, port, ofport, table, action, group, or VLAN behavior

Specific requirements:

1. Every OVS hop in the conclusion must cite the concrete flow(s) involved, identified by at least: `bridge`, `table`, key `match` fields, and `actions`. Include `cookie` or flow index when available.
2. Do not stop at "traffic enters br-int" or "wan1 port is up". Always continue to "which flow in which table on which bridge decides what happens, and what its actions are".
3. If `fpe_analyze_flow` returns an OVS-related path, immediately follow up with `fpe_get_ovs_flows` to materialize the exact flow entries referenced by that path. Do not rely on the analyzer summary alone.
4. If the exact matched flow cannot be determined, explicitly label entries as `candidate flow` and list every candidate flow with full `table / match / actions`, plus the reason exact match is unproven.
5. Never describe OVS behavior using only bridge name, port name, ofport, or VLAN tag. These are attributes; the flow is the decision.
6. Counter-only evidence (`n_packets > 0`) is not enough by itself, and must never be used as the primary basis for inferring a match. Counters are validation signals only — they confirm an already-identified path during live traffic, they do not establish which flow or bucket was selected. Always pair counter evidence with the concrete flow's `match` and `actions`. A zero counter does not disprove a path; the environment may have no live traffic at analysis time.
7. Multi-table pipelines must be expanded table by table. Do not collapse `table=0 -> ... -> output` into a single arrow; each table transition must show the flow that performed it (or be marked as an inferred candidate per table).
8. When `resubmit`, `goto_table`, `learn`, `conjunction`, `ct`, `output:NXM`, `controller`, or `group:<id>` actions are involved, the report must name the action explicitly and trace the next table/flow/group.
9. If any flow action references a group (e.g. `group:1`, `actions=group:N`), the analysis MUST also dump and inspect that group's buckets — do not stop at the flow that points to the group.

## Default workflow

### 1. Define the packet first

Before calling any detailed tool, identify as many of these fields as possible:

- `src_ip`
- `dst_ip`
- `ingress_if`
- `protocol`
- `src_port`
- `dst_port`
- `vlan_id`
- `tunnel_id`
- `fwmark`
- `namespace`
- `vrf`

If key packet fields are missing, say what is assumed before reasoning from tools.

### 2. Prefer the main analyzer first

First choice:

- `fpe_analyze_flow`

Use it when the goal is any of:

- explain actual forwarding path
- find where traffic deviates
- build a traffic chain diagram
- summarize risks quickly

Minimum useful input:

```json
{
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "ingress_if": "lan1"
  },
  "exec_ctx": {
    "namespace": "ns_app",
    "vrf": "vrf-app"
  }
}
```

Read these fields first from the result:

- `status`
- `summary`
- `path`
- `risks`
- `graph`
- `mermaid`

If `analyze_flow` already explains the issue clearly, do not fan out into many raw tools.

### 3. Drill down only to answer a specific uncertainty

Use raw tools only when one part of the main path is still unclear.

#### A. Need topology or ownership confirmation

Use:

- `fpe_get_interface_context`

Questions it answers:

- Which namespace / VRF is this interface in?
- Is this a physical port, veth, bridge port, VRF member, or tunnel?
- Is the interface up?

Typical filters:

```json
{
  "iface": "lan1",
  "state": "UP"
}
```

#### B. Need OVS bridge / port relationship

Use:

- `fpe_get_ovs_bridges`

Questions it answers:

- Which bridge contains `lan1`?
- What is the port name and ofport?
- Is it access VLAN, trunk, internal, or tunnel?

Typical filters:

```json
{
  "interface": "lan1"
}
```

If you also need the bridge's flow inventory:

```json
{
  "interface": "lan1",
  "include_flows": true
}
```

#### C. Need exact flow candidates

Use:

- `fpe_get_ovs_flows`

This is the main drill-down tool for OVS dataplane reasoning.

Questions it answers:

- Which flows on the relevant bridge could match this packet?
- Are those flows active?
- Which table is important?

Preferred call shape:

```json
{
  "ingress_if": "lan1",
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "ingress_if": "lan1",
    "protocol": "icmp",
    "vlan_id": 10
  },
  "active_only": true
}
```

Read these fields first:

- `matched_flows`
- `flows`
- `bridge`

Prefer `matched_flows` over scanning all raw flows manually.

#### C2. Need OVS group table inspection (dump-groups)

Use when any matched or candidate flow's `actions` contains `group:<id>`, or when the topology hints at ECMP / failover / select / multicast handled by OVS group buckets.

Tool / commands:

- `fpe_get_ovs_groups` (preferred MCP tool when available)
- Fallback shell evidence: `ovs-ofctl -O OpenFlow15 dump-groups <bridge>` and `ovs-ofctl -O OpenFlow15 dump-group-stats <bridge> [group_id]`

Questions it answers:

- Which group IDs exist on the bridge, and of what type (`all`, `select`, `indirect`, `ff` / fast-failover)?
- What are the buckets, their weights, watch_port / watch_group, and per-bucket actions?
- Which bucket is currently live (especially for `ff` groups) or which buckets are eligible (for `select`)?
- Are bucket counters incrementing (per-bucket `packet_count` / `byte_count`)?

Preferred call shape:

```json
{
  "bridge": "br-wan1",
  "group_id": 1,
  "include_stats": true
}
```

Read these fields first:

- `group_id`
- `type`
- `buckets[].weight`
- `buckets[].watch_port`
- `buckets[].watch_group`
- `buckets[].actions`
- `buckets[].packet_count`
- `selected_bucket` (if the tool reports it)

Hard rules for group reasoning:

1. A flow with `actions=group:N` is NOT a terminal conclusion. The report must show what `group N` does, bucket by bucket.
2. For `select` groups, identify which buckets are eligible and (if statistics allow) which bucket actually carries the test traffic. Without bucket-level counter evidence, label the choice as `candidate bucket`.
3. For `ff` (fast-failover) groups, the live bucket is determined by `watch_port` / `watch_group` liveness. The report must state which watched port/group is up and therefore which bucket is selected, citing interface state evidence.
4. For `all` groups, list every bucket as an active output path — do not silently pick one.
5. Group buckets that themselves contain `resubmit`, `goto_table`, `output:`, or another `group:` action must be traced further per the multi-table rule above.
6. Treat group existence alone as insufficient evidence; always pair it with the upstream flow that selects it and the downstream action of the chosen bucket.

#### D. Need kernel policy routing explanation

Use:

- `fpe_get_rule`

Only after evidence suggests traffic entered kernel L3.

Questions it answers:

- Which rules match this packet?
- Which rule wins?
- Which table should be consulted next?

Preferred call:

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "packet": {
    "src_ip": "10.0.0.2",
    "dst_ip": "8.8.8.8",
    "ingress_if": "lan1",
    "fwmark": "0x10"
  }
}
```

Read:

- `selected_rule`
- `matched_rules`

#### E. Need final route choice

Use:

- `fpe_get_route`

Questions it answers:

- What is the best route for this destination?
- Which egress device is actually selected?

Preferred call:

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "dst_ip": "8.8.8.8",
  "best_only": true
}
```

If validating a specific egress:

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "device": "wan0"
}
```

#### F. Need next-hop reachability confirmation

Use:

- `fpe_get_neighbor`

Questions it answers:

- Does the next hop exist?
- Is it reachable or failed?

Preferred call:

```json
{
  "namespace": "ns_app",
  "vrf": "vrf-app",
  "device": "wan0",
  "target_ip": "192.168.1.1"
}
```

## Decision tree

If the user asks "why didn't traffic go out as expected?":

1. Call `fpe_analyze_flow`.
2. If result shows OVS drop or OVS mismatch, stay in OVS tools.
3. If result shows kernel handoff, then inspect `get_rule`, `get_route`, `get_neighbor`.

If the user asks "which flow handled this traffic?":

1. Call `fpe_get_ovs_flows` with `ingress_if` plus `packet`.
2. If too broad, add `table`, `vlan_id`, `protocol`, ports, or `active_only`.

If the user asks "which bridge owns this interface?":

1. Call `fpe_get_ovs_bridges` with `interface`.
2. If still unclear, confirm interface role via `get_interface_context`.

If the user asks "is this a route problem or an OVS problem?":

1. Start with `fpe_analyze_flow`.
2. If path stops before kernel, classify as OVS-side.
3. If path reaches kernel and then diverges, classify as L3-side.

## Output style

Always convert tool evidence into these three layers:

1. Path conclusion
2. Deviation point
3. Supporting evidence

Preferred answer shape:

- Expected path: `lan1 -> br-int -> tunnel0`
- Actual path: `lan1 -> br-int -> table 0 flow -> LOCAL -> rule 100 -> wan0`
- Deviation: OVS handed traffic to kernel instead of tunnel port
- Evidence: matched flow X, selected rule Y, best route Z

Do not dump raw tool JSON unless the user explicitly asks for it.

## Markdown report rules

When producing a flow-analysis markdown document, do not write it like a fully proven packet trace unless the tools actually proved it.

The report must separate:

1. Confirmed evidence
2. High-confidence inference
3. Assumptions or unresolved gaps

### Required certainty labels

Use explicit wording:

- `Confirmed`: directly supported by tool output
- `Inferred`: derived from multiple tool outputs or standard forwarding behavior
- `Unconfirmed`: plausible but not closed by current evidence

Avoid absolute wording like:

- `无偏差`
- `完整匹配`
- `已确认最终命中`
- `路径完全闭合`

unless every key forwarding transition is directly supported.

Prefer wording like:

- `当前未发现明显偏差`
- `现有证据支持该路径`
- `OVS 候选命中链如下`
- `根据规则和路由结果推断`
- `该段仍需进一步确认`

### Required report structure

When generating a markdown report, use this order:

1. Packet definition
2. Final conclusion
3. Confidence and gaps
4. Hop-by-hop evidence
5. Monitoring and validation guidance
6. If needed, path graph
7. Tool limitations or contradictions

### Final conclusion rules

The final conclusion section must contain:

1. `Expected path` if the user provided an expectation
2. `Observed path` based on evidence
3. `Deviation point` or `No clear deviation found yet`
4. `Confidence` with a short explanation

If there is any unresolved tool contradiction, do not conclude `no deviation`.

Instead say:

- `No clear forwarding deviation is proven by current evidence`
- `The current data supports this path, but tool gaps remain`

### OVS flow reporting rules

Any mention of OVS in the report MUST be specific to the individual flow entry (and group bucket when groups are involved). A report that names only the bridge, port, table, or VLAN — without the matching flow's `table / match / actions` — is incomplete and must be revised before publishing.

Do not treat:

- `n_packets > 0`
- broad wildcard flows
- generic `ip` rules
- table-local active counters
- "bridge contains the port"
- "table X exists"
- "group X exists"

as proof that the current packet matched that exact flow or that the listed group bucket was selected.

For OVS sections:

1. Prefer `matched_flows` from `fpe_get_ovs_flows` when available.
2. If exact packet match is unavailable, label the chain as `candidate flow path` and still enumerate each candidate flow's full `table / match / actions`.
3. For every flow that uses `group:<id>`, include a sub-listing of the group's buckets from `fpe_get_ovs_groups` (or `ovs-ofctl dump-groups`) with `type`, `weight`, `watch_port`, and `actions`.
4. Distinguish:
   - `active flow`
   - `candidate matching flow`
   - `confirmed selected flow`
   - `selected group bucket` vs `candidate group bucket`

Use this wording model:

- `Confirmed selected flow`: only if packet-specific match evidence exists.
- `Candidate flow`: if inferred from ingress port, table progression, and active counters.
- `Background active flow`: if merely observed in the bridge.

### Rule and route reporting rules

Do not collapse Linux routing behavior into a single `selected_rule` statement if the actual result depends on fallthrough semantics.

If `local` is selected first but the destination is not a local address, write:

- `Confirmed`: rule priority 0 points to local table
- `Inferred`: destination is not resolved in local table, so lookup continues per kernel behavior

Do not present this as if the tool already executed a full rule-walk unless it did.

### Bridge/VLAN reporting rules

Do not assume port VLAN configuration equals the packet's actual wire-format state.

Differentiate:

1. Port configuration
2. Flow action behavior
3. Packet state actually proven for this flow

Prefer:

- `wan1 port is configured with tag 2004`

instead of:

- `the packet exits with VLAN 2004`

unless flow/action evidence closes that gap.

### Contradiction handling

If one tool says incomplete but the combined evidence suggests a likely path:

1. State the tool limitation explicitly
2. Preserve the likely path
3. Lower certainty
4. Name the unresolved point

Use this pattern:

- `Tool result`: analyze_flow returned `INCOMPLETE`
- `Likely path`: ...
- `Reason for discrepancy`: ...
- `Residual uncertainty`: ...

## Monitoring and validation rules

This version is a static analysis workflow, not a real-time monitoring system.

Therefore every markdown report must include a short section that answers:

1. What should be monitored
2. Where to monitor it
3. What signal would validate the inferred path
4. What signal would falsify the inferred path

Do not stop at “current evidence suggests ...”.
Also explain how an operator can verify it on a live system.

### Required monitoring section

Include a section like:

- `Monitoring points`
- `Monitoring priority`
- `How to validate`
- `What would indicate deviation`

### What to monitor

Choose only the checkpoints that matter for the inferred path:

1. Ingress interface counters
2. OVS bridge / port counters
3. Specific OVS flow counters
4. Kernel route usage context
5. Neighbor state changes
6. Tunnel interface counters
7. BGP route presence or next-hop validity if the path depends on BGP

### Monitoring priority levels

Monitoring guidance must be tiered.

Do not present all checkpoints as equally important.

Use these levels:

#### Level 1: Traffic steering decision points

This is the highest priority and must always be present.

These are the places that decide where traffic will go:

1. OVS table / flow that performs first meaningful classification
2. OVS table / flow that performs final output decision
3. Kernel rule that selects routing context if traffic enters L3
4. Route lookup result or route table that decides the egress device

If a report does not identify Level 1 monitoring points, the monitoring section is incomplete.

#### Level 2: Path continuity checkpoints

Use these to confirm traffic continues after the steering decision:

1. Ingress interface counters
2. Intermediate veth / patch / internal port counters
3. Tunnel port counters
4. Egress port counters

#### Level 3: Reachability and external dependency checks

Use these to confirm the chosen path is usable:

1. Neighbor reachability
2. Underlay next-hop state
3. Tunnel underlay route
4. BGP-derived FIB presence and next-hop validity

### Where to monitor

The report should explicitly say the observation location, for example:

1. Specific namespace
2. Specific VRF
3. Specific OVS bridge
4. Specific OVS port or ofport
5. Specific route table
6. Specific next-hop neighbor entry

If the path crosses from business namespace / VRF into the host namespace, explicitly separate:

1. Business-side observation point
2. Host-side observation point

Use the term `host namespace` or `root namespace` consistently when describing the宿主机侧观察点.

Avoid vague phrases like:

- `observe OVS`
- `check route`

Prefer:

- `watch flow counters on bridge br-wan1 table 30 and table 50`
- `watch neighbor 10.220.21.254 on device br-wan1 in root namespace`
- `watch route resolution for 8.8.8.8 in namespace ANPOSNS / VRF Vrf262147Ns`

### Host-side monitoring rule

When the inferred path leaves a tenant namespace, VRF, or service namespace and crosses into the host side, the report must explicitly describe how to monitor on the host.

At minimum include, when applicable:

1. Which host-side interface receives the traffic after cross-namespace transfer
2. Which host-side route or bridge becomes authoritative
3. Which host-side OVS bridge / port / flow should be watched
4. Which host-side next-hop neighbor validates final reachability

Use wording like:

- `Namespace side`: monitor route selection on `wan1-r` in `ANPOSNS / Vrf262147Ns`
- `Host side`: monitor OVS flow counters on `br-wan1` and egress port `wan1` in root namespace

Do not stop at namespace-side monitoring if the decisive output happens on the host.

### Validation wording

For each important hop, provide:

1. `Expected live signal`
2. `Validation meaning`
3. `Failure meaning`

Use this style:

- `Monitor`: OVS flow counter for `table=50, reg11=0x1, actions=output:1`
- `Where`: bridge `br-wan1`
- `Expected signal`: counter increases when test traffic is generated
- `Validates`: traffic is leaving OVS through `wan1`
- `If not seen`: traffic is being diverted, dropped earlier, or matching a different flow

When Level 1 steering is present, list those Level 1 monitors before any counter or neighbor details.

### Minimum validation coverage

If the report concludes a path, include validation points for at least:

1. The ingress point
2. The Level 1 steering table / rule / flow
3. The decisive OVS flow or OVS action
4. The final egress step

If kernel L3 is involved, also include:

1. Rule/table selection context
2. Route/egress device
3. Next-hop neighbor state

If traffic crosses into the host namespace, also include:

1. The host-side first authoritative decision point
2. The host-side final output decision point

### Candidate-path validation rule

If a flow chain is only inferred, the monitoring section must say so explicitly.

Use phrasing like:

- `This path is currently inferred from active flows and topology.`
- `The most important live validation point is whether flow X counter increases with the test packet.`

Do not present monitoring as optional when certainty is low.

### Steering-first reporting rule

The first monitor listed in the markdown should usually be the steering point, not the ingress interface counter.

Bad order:

1. ingress packet counter
2. neighbor state
3. final route
4. decisive flow

Preferred order:

1. decisive steering table / flow / rule
2. final output table / flow / route
3. ingress and continuity counters
4. neighbor and reachability checks

### Tunnel and BGP specific validation

If the report mentions tunnel or BGP egress, include targeted validation advice:

For tunnel paths:

1. Monitor tunnel port counters
2. Monitor underlay route and neighbor to the tunnel next hop
3. State that tunnel port existence alone does not validate traffic selection

For BGP-dependent paths:

1. Verify the expected route is present in FIB
2. Verify the expected next hop is resolvable
3. State that control-plane presence and data-plane forwarding are separate validations

### Real-time limitation wording

If the user may interpret the report as a live monitor, include one sentence like:

- `This report is based on snapshot data, not continuous monitoring; the validation points above should be watched during live traffic tests to confirm the inferred path.`

### Mermaid rules

In Mermaid diagrams:

1. Use only confirmed nodes and high-confidence inferred nodes.
2. If a segment is inferred, include that in the node or edge label.
3. Do not draw an apparently deterministic straight-line path if one step is still only a candidate.

Preferred labels:

- `OVS candidate flow chain`
- `kernel L3 lookup (inferred)`
- `route to wan1-r (confirmed)`

## Chain graph guidance

When the goal is a flow diagram:

1. Prefer `fpe_analyze_flow` first because it already returns `graph` and `mermaid`.
2. Use raw tools only to refine uncertain segments.
3. Keep graph narrative aligned with forwarding order:
   - ingress interface
   - ovs bridge
   - ovs port
   - ovs flow/table
   - action result
   - kernel rule/route/neighbor if present
   - final egress

## Counter usage rule: counters validate, never infer

Packet and byte counters — whether on OVS flows, OVS ports, OVS groups, kernel interfaces, or route entries — are **validation signals only**.

They must never be used as the primary basis for inferring which path traffic took, which flow was matched, or which group bucket was selected.

### Why

The target environment is not guaranteed to have live traffic at the time of analysis. A counter value of zero does not mean the path is wrong. A counter value greater than zero does not mean the current packet matched that specific entry — it only means some traffic incremented it at some point in the past.

### What counters can do

| Use | Allowed |
|-----|---------|
| Confirm that a previously inferred path is active during a live test | ✅ Yes |
| Raise or lower confidence in a candidate flow after the flow is already identified by match fields | ✅ Yes |
| Distinguish between two equally plausible candidate flows when both match fields and counters are compared together | ✅ Yes (with explicit caveat) |
| Serve as the sole reason to conclude a flow was matched | ❌ No |
| Serve as the sole reason to conclude a group bucket was selected | ❌ No |
| Substitute for missing `match` / `actions` evidence | ❌ No |
| Prove a path is correct when the environment has no current traffic | ❌ No |

### Required wording when counters are cited

When citing a counter as supporting evidence, always pair it with the flow's `match` and `actions`, and use one of these labels:

- `Counter supports inference` — the flow was already identified by match fields; the counter is consistent with it being active.
- `Counter is inconclusive` — the counter is non-zero but the exact packet match is unproven; the flow remains a candidate.
- `Counter is zero; path not falsified` — zero counter in a static snapshot does not disprove the path.

Never write:

- `n_packets > 0, therefore this flow handled the traffic`
- `counter is incrementing, so this bucket is selected`
- `no counter activity, so traffic did not take this path`

### Impact on path conclusions

If the only evidence for a forwarding hop is a non-zero counter, that hop must be labeled `Unconfirmed` in the report, not `Confirmed` or `Inferred`.

The path conclusion must be built from:

1. Flow `match` fields that align with the packet definition
2. Flow `actions` that explain the next hop
3. Topology evidence (bridge membership, port role, namespace, VRF)
4. Rule and route lookup results when kernel L3 is involved

Counters may then be listed as secondary corroboration, clearly labeled as such.

### Impact on monitoring guidance

Because counters are validation signals, the monitoring section of a report should instruct the operator to watch counters **during a live test**, not treat current snapshot counter values as proof.

Use wording like:

- `Generate test traffic, then check whether this flow's counter increments — that would validate the inferred path.`
- `A zero counter in the current snapshot does not disprove this path; the environment may have no active traffic right now.`

## Common mistakes to avoid

1. Starting with `get_route` before knowing whether OVS forwarded to kernel.
2. Querying all flows on all bridges without first finding the ingress bridge.
3. Ignoring `namespace` / `vrf`.
4. Treating broad collected data as proof without packet-specific matching.
5. Returning raw tool results without stating the actual path conclusion.
6. Calling a path `confirmed` when the report is really based on active-flow inference.
7. Writing `无偏差` while still documenting unresolved analyzer contradictions.
8. Describing OVS behavior at bridge/port/table granularity without naming the specific flow's `match` and `actions`.
9. Stopping at a flow whose action is `group:<id>` without dumping that group's buckets and identifying the selected (or candidate) bucket.
10. Treating group existence or bucket existence as proof of selection without `watch_port` liveness (for `ff`) or per-bucket counter evidence (for `select`).
11. Using a non-zero counter as the primary reason to conclude a flow was matched or a bucket was selected — counters validate, they do not infer.
12. Treating a zero counter as proof that traffic did not take a path — the environment may simply have no live traffic at analysis time.
13. Skipping `match` / `actions` evidence and substituting counter activity as the forwarding explanation.
