"""Sample command outputs for testing collectors."""

IP_LINK_SHOW_ETH0 = """
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
"""

IP_LINK_SHOW_VETH0 = """
3: veth0@veth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff
    veth
    peer veth1
"""

IP_LINK_SHOW_BRIDGE = """
4: br0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
    bridge
"""

IP_ADDR_SHOW_ETH0 = """
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    inet 192.168.1.10/24 brd 192.168.1.255 scope global eth0
    inet6 fe80::211:22ff:fe33:4455/64 scope link
"""

IP_RULE_SHOW = """
0:    from all lookup local
100:    from 10.0.0.2 lookup 100
200:    from all to 8.8.8.8 lookup 200
32766:    from all lookup main
32767:    from all lookup default
"""

IP_ROUTE_SHOW = """
default via 192.168.1.1 dev eth0 metric 100
10.0.0.0/24 dev eth0 proto kernel scope link src 10.0.0.2 metric 100
192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.10 metric 100
"""

IP_ROUTE_SHOW_TABLE_100 = """
10.0.0.0/8 via 10.0.1.1 dev veth0 metric 50
"""

IP_NEIGH_SHOW = """
192.168.1.1 dev eth0 llac 00:11:22:33:44:55 REACHABLE
192.168.1.2 dev eth0 llac 00:11:22:33:44:66 STALE
192.168.1.3 dev eth0  FAILED
"""

OVS_VSCTL_SHOW = """
0a1b2c3d-4e5f-6789-abcd-ef0123456789
    Bridge "br-int"
        Port "br-int"
            Interface "br-int"
                type: internal
        Port "veth0"
            Interface "veth0"
        Port "tap10"
            tag: 10
            Interface "tap10"
        Port "trunk-port"
            trunks: [10, 20, 30]
            Interface "trunk-port"
"""

OVS_OFCTL_SHOW_BR_INT = """
OFPT_FEATURES_REPLY (xid=0x2): dpid:0000aabbccddeeff
n_tables:254, n_buffers:0
capabilities: FLOW_STATS TABLE_STATS PORT_STATS QUEUE_STATS ARP_MATCH_IP
 1(veth0): addr:aa:bb:cc:dd:ee:01
     config:     0
     state:      0
     current:    10GB-FD COPPER
     speed: 10000 Mbps now, 0 Mbps max
 2(tap10): addr:aa:bb:cc:dd:ee:02
     config:     0
     state:      0
     current:    10GB-FD COPPER
     speed: 10000 Mbps now, 0 Mbps max
 3(trunk-port): addr:aa:bb:cc:dd:ee:03
     config:     0
     state:      0
     current:    10GB-FD COPPER
     speed: 10000 Mbps now, 0 Mbps max
 LOCAL(br-int): addr:aa:bb:cc:dd:ee:ff
     config:     0
     state:      0
     current:    10GB-FD COPPER
     speed: 10000 Mbps now, 0 Mbps max
"""

OVS_OFCTL_DUMP_FLOWS_BR_INT = """
 cookie=0x0, duration=12345.678s, table=0, n_packets=1000, n_bytes=100000, idle_age=5, priority=100,arp actions=CONTROLLER:65535
 cookie=0x1, duration=1000.500s, table=0, n_packets=50, n_bytes=5000, idle_age=10, priority=50,ip,nw_dst=10.0.0.0/24 actions=output:2
 cookie=0x2, duration=500.250s, table=0, n_packets=0, n_bytes=0, idle_age=500, priority=10 actions=drop
"""

IP_NETNS_LIST = """
ns_app
ns_edge
"""

IP_LINK_SHOW_HOST_ALL = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: veth-host@veth-app: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    link/ether aa:aa:aa:aa:aa:01 brd ff:ff:ff:ff:ff:ff
    veth
    peer veth-app
3: veth-edge@veth-node: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    link/ether aa:aa:aa:aa:aa:02 brd ff:ff:ff:ff:ff:ff
    veth
    peer veth-node
"""

IP_LINK_SHOW_NS_APP_ALL = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: vrf-app: <NOARP,MASTER,UP,LOWER_UP> mtu 65536 state UP
    link/ether 02:00:00:00:00:01 brd ff:ff:ff:ff:ff:ff
    vrf table 1001
3: veth-app@veth-host: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master vrf-app state UP
    link/ether bb:bb:bb:bb:bb:01 brd ff:ff:ff:ff:ff:ff
    veth
    peer veth-host
"""

IP_LINK_SHOW_NS_EDGE_ALL = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: veth-node@veth-edge: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    link/ether cc:cc:cc:cc:cc:01 brd ff:ff:ff:ff:ff:ff
    veth
    peer veth-edge
"""

IP_ADDR_SHOW_HOST = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    inet 127.0.0.1/8 scope host lo
2: veth-host@veth-app: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 10.0.0.1/24 scope global veth-host
3: veth-edge@veth-node: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 10.0.1.1/24 scope global veth-edge
"""

IP_ADDR_SHOW_NS_APP = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    inet 127.0.0.1/8 scope host lo
2: vrf-app: <NOARP,MASTER,UP,LOWER_UP> mtu 65536 state UP
3: veth-app@veth-host: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 10.0.0.2/24 scope global veth-app
"""

IP_ADDR_SHOW_NS_EDGE = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN
    inet 127.0.0.1/8 scope host lo
2: veth-node@veth-edge: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP
    inet 10.0.1.2/24 scope global veth-node
"""
