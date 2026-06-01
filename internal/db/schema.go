package db

const Schema = `
CREATE TABLE IF NOT EXISTS interfaces (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    namespace  TEXT NOT NULL DEFAULT '',
    vrf        TEXT NOT NULL DEFAULT '',
    ifindex    INTEGER NOT NULL DEFAULT 0,
    kind       TEXT,
    state      TEXT,
    flags      TEXT NOT NULL DEFAULT '[]',
    mac        TEXT,
    mtu        INTEGER,
    master     TEXT,
    peer       TEXT,
    peer_index INTEGER NOT NULL DEFAULT 0,
    ips        TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace   TEXT NOT NULL DEFAULT '',
    vrf         TEXT NOT NULL DEFAULT '',
    priority    INTEGER NOT NULL,
    from_prefix TEXT,
    table_id    TEXT NOT NULL,
    fwmark      TEXT,
    action      TEXT
);

CREATE TABLE IF NOT EXISTS routes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace     TEXT NOT NULL DEFAULT '',
    vrf           TEXT NOT NULL DEFAULT '',
    table_id      TEXT NOT NULL DEFAULT 'main',
    prefix        TEXT NOT NULL,
    preferred_src TEXT,
    metric        INTEGER NOT NULL DEFAULT 0,
    protocol      TEXT NOT NULL DEFAULT '',
    scope         TEXT NOT NULL DEFAULT '',
    route_type    TEXT,
    flags         TEXT NOT NULL DEFAULT '[]',
    next_hops     TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS neighbors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT '',
    vrf       TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL,
    dev       TEXT NOT NULL,
    mac       TEXT,
    state     TEXT,
    reachable BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ovs_bridges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    datapath_id   TEXT,
    datapath_type TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS ovs_ports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bridge      TEXT NOT NULL,
    port        TEXT NOT NULL,
    interface   TEXT,
    port_type   TEXT NOT NULL DEFAULT 'system',
    ofport      INTEGER,
    vlan_tag    INTEGER,
    trunk_vlans TEXT NOT NULL DEFAULT '[]',
    mac         TEXT,
    options     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ovs_flows (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bridge       TEXT NOT NULL,
    table_id     INTEGER NOT NULL,
    priority     INTEGER NOT NULL DEFAULT 0,
    cookie       TEXT,
    match        TEXT NOT NULL,
    actions      TEXT NOT NULL,
    match_fields TEXT NOT NULL DEFAULT '{}',
    action_list  TEXT NOT NULL DEFAULT '[]',
    n_packets    INTEGER,
    n_bytes      INTEGER
);

CREATE TABLE IF NOT EXISTS ovs_groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bridge       TEXT NOT NULL,
    group_id     INTEGER NOT NULL,
    group_type   TEXT NOT NULL,
    packet_count INTEGER NOT NULL DEFAULT 0,
    byte_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ovs_group_buckets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_fk     INTEGER NOT NULL REFERENCES ovs_groups(id),
    bucket_id    INTEGER NOT NULL,
    weight       INTEGER NOT NULL DEFAULT 1,
    actions      TEXT NOT NULL,
    action_list  TEXT NOT NULL DEFAULT '[]',
    watch_port   INTEGER,
    watch_group  INTEGER,
    active       BOOLEAN,
    packet_count INTEGER NOT NULL DEFAULT 0,
    byte_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ovs_fdb (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bridge  TEXT NOT NULL,
    port    TEXT NOT NULL,
    vlan    INTEGER NOT NULL DEFAULT 0,
    mac     TEXT NOT NULL,
    age_sec INTEGER
);

CREATE TABLE IF NOT EXISTS ovs_tnl_arp (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    bridge TEXT NOT NULL,
    ip     TEXT NOT NULL,
    mac    TEXT NOT NULL,
    port   TEXT
);

CREATE INDEX IF NOT EXISTS idx_interfaces_ns    ON interfaces(namespace, vrf, name);
CREATE INDEX IF NOT EXISTS idx_rules_ns         ON rules(namespace, vrf, priority);
CREATE TABLE IF NOT EXISTS frr_info (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL UNIQUE,
    output  TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'ok'
);

CREATE INDEX IF NOT EXISTS idx_routes_ns_table  ON routes(namespace, vrf, table_id);
CREATE INDEX IF NOT EXISTS idx_neighbors_ip     ON neighbors(ip);
CREATE INDEX IF NOT EXISTS idx_ovs_ports_bridge ON ovs_ports(bridge, port);
CREATE INDEX IF NOT EXISTS idx_flows_table      ON ovs_flows(bridge, table_id, priority DESC);
CREATE INDEX IF NOT EXISTS idx_groups_id        ON ovs_groups(bridge, group_id);
CREATE INDEX IF NOT EXISTS idx_ovs_fdb_mac      ON ovs_fdb(bridge, mac);
CREATE INDEX IF NOT EXISTS idx_ovs_tnl_arp_ip   ON ovs_tnl_arp(bridge, ip);
`
