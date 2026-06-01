package collector

func buildNSCmd(namespace, cmd string) string {
	if namespace != "" {
		return "ip netns exec " + namespace + " " + cmd
	}
	return cmd
}
