package ssh

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

type SSHConnectivityTester struct {
	baseCommand []string
	sshKeyPath  string
	username    string
}

func NewSSHConnectivityTester(workingDirectory string) *SSHConnectivityTester {
	sshKeyPath := filepath.Join(workingDirectory, SSHUserPrivateKeyFileName)
	knownHostsFilePath := filepath.Join(workingDirectory, SSHKnownHostsFileName)
	baseCommand := []string{
		"ssh",
		"-o",
		"BatchMode=yes",
		"-o",
		"LogLevel=ERROR",
		"-o",
		"PasswordAuthentication=no",
		"-o",
		"StrictHostKeyChecking=yes",
		"-o",
		fmt.Sprintf("UserKnownHostsFile=%s", knownHostsFilePath),
		"-o",
		fmt.Sprintf("HostKeyAlias=%s-key", VMHostName),
		"-o",
		"IdentitiesOnly=yes",
		"-p",
		"22",
		"-i",
		sshKeyPath,
	}

	return &SSHConnectivityTester{
		baseCommand: baseCommand,
		sshKeyPath:  sshKeyPath,
		username:    VMUser,
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

	command := append([]string{}, t.baseCommand...)
	command = append(command, "-o", fmt.Sprintf("ConnectTimeout=%d", timeout), fmt.Sprintf("%s@%s", t.username, ipAddress), "true")

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, command[0], command[1:]...)

	if err := cmd.Run(); err != nil {
		return false, nil
	}

	return true, nil
}
