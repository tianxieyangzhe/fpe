package collector

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"strings"

	"github.com/yangshuai/fpe/internal/logs"
	"golang.org/x/crypto/ssh"
)

type Executor interface {
	Run(cmd string) (string, error)
}

// LocalExecutor runs commands on the local machine.
type LocalExecutor struct{}

func (e *LocalExecutor) Run(cmd string) (string, error) {
	out, err := exec.Command("bash", "--login", "-c", cmd).Output()
	logs.Debugf("run cmd=%q error=%v", cmd, err)
	if err != nil {
		return "", fmt.Errorf("%s: %w", cmd, err)
	}
	return strings.TrimSpace(string(out)), nil
}

// SSHExecutor runs commands on a remote machine via SSH.
type SSHExecutor struct {
	client *ssh.Client
}

func NewSSHExecutor(host, user, keyPath string) (*SSHExecutor, error) {
	key, err := readPrivateKey(keyPath)
	if err != nil {
		return nil, err
	}
	cfg := &ssh.ClientConfig{
		User:            user,
		Auth:            []ssh.AuthMethod{ssh.PublicKeys(key)},
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
	}
	if !strings.Contains(host, ":") {
		host += ":22"
	}
	client, err := ssh.Dial("tcp", host, cfg)
	if err != nil {
		return nil, err
	}
	return &SSHExecutor{client: client}, nil
}

func (e *SSHExecutor) Run(cmd string) (string, error) {
	sess, err := e.client.NewSession()
	if err != nil {
		return "", err
	}
	defer sess.Close()
	var buf bytes.Buffer
	sess.Stdout = &buf
	if err := sess.Run("bash -l -c " + "'" + cmd + "'"); err != nil {
		logs.Debugf("run cmd=%q error=%v", cmd, err)
		return "", fmt.Errorf("%s: %w", cmd, err)
	}
	out := strings.TrimSpace(buf.String())
	logs.Debugf("run cmd=%q", cmd)
	return out, nil
}

func (e *SSHExecutor) Close() error { return e.client.Close() }

func readPrivateKey(path string) (ssh.Signer, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return ssh.ParsePrivateKey(data)
}
