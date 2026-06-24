package ssh

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/crypto/ssh"
	"golang.org/x/crypto/ssh/knownhosts"
)

type SSHConnectivityTester struct {
	knownHostsFilePath string
	sshKeyPath         string
	username           string
}

func NewSSHConnectivityTester(workingDirectory string) *SSHConnectivityTester {
	return &SSHConnectivityTester{
		knownHostsFilePath: filepath.Join(workingDirectory, SSHKnownHostsFileName),
		sshKeyPath:         filepath.Join(workingDirectory, SSHUserPrivateKeyFileName),
		username:           VMUser,
	}
}

func (t *SSHConnectivityTester) TestConnectivity(ipAddress string, timeout int) (bool, error) {
	_, err := os.Stat(t.sshKeyPath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, fmt.Errorf("file does not exist: %w", err)
		}
		return false, err
	}

	keyBytes, err := os.ReadFile(t.sshKeyPath)
	if err != nil {
		return false, fmt.Errorf("failed to read private key: %w", err)
	}

	signer, err := ssh.ParsePrivateKey(keyBytes)
	if err != nil {
		return false, fmt.Errorf("failed to parse private key: %w", err)
	}

	hostKeyCallback, err := knownhosts.New(t.knownHostsFilePath)
	if err != nil {
		return false, fmt.Errorf("failed to load known hosts file: %w", err)
	}

	wrappedHostKeyCallback := func(hostname string, remote net.Addr, key ssh.PublicKey) error {
		alias := fmt.Sprintf("%s-key:22", VMHostName)
		return hostKeyCallback(alias, remote, key)
	}

	config := &ssh.ClientConfig{
		Auth: []ssh.AuthMethod{
			ssh.PublicKeys(signer),
		},
		HostKeyCallback: wrappedHostKeyCallback,
		Timeout:         time.Duration(timeout) * time.Second,
		User:            t.username,
	}

	addr := net.JoinHostPort(ipAddress, "22")
	client, err := ssh.Dial("tcp", addr, config)
	if err != nil {
		return false, nil
	}

	client.Close()

	return true, nil
}
