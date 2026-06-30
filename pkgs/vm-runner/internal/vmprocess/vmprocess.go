package vmprocess

import (
	"bufio"
	crand "crypto/rand"
	"errors"
	"fmt"
	"io"
	"log/slog"
	mrand "math/rand/v2"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"vm-runner/internal/api"
	"vm-runner/internal/circuitbreaker"
	"vm-runner/internal/config"
	"vm-runner/internal/ipdiscovery"
	"vm-runner/internal/ssh"
)

type VMProcessState string

const (
	VMProcessStatePaused  VMProcessState = "paused"
	VMProcessStateRunning VMProcessState = "running"
	VMProcessStateStopped VMProcessState = "stopped"
	VMProcessStateUnknown VMProcessState = "unknown"
)

var vfkitBin = "vfkit"

type VMProcess struct {
	apiClient         *api.APIClient
	apiPort           int
	circuitBreaker    *circuitbreaker.CircuitBreaker
	config            *config.VMConfig
	ipAddress         string
	ipDiscovery       *ipdiscovery.IPDiscovery
	macAddress        string
	mu                sync.Mutex
	outputCh          chan struct{}
	pidFile           string
	processExitCh     chan struct{}
	shutdownRequested atomic.Bool
	command           *exec.Cmd
}

func generateMacAddress() string {
	b := make([]byte, 4)
	crand.Read(b)
	prefix := "02:94"
	suffix := fmt.Sprintf("%02x:%02x:%02x:%02x", b[0], b[1], b[2], b[3])

	return fmt.Sprintf("%s:%s", prefix, suffix)
}

func consumeVMProcessOutput(stdout, stderr io.ReadCloser, ch chan struct{}) {
	defer close(ch)

	var wg sync.WaitGroup

	readStream := func(stream io.ReadCloser) {
		defer wg.Done()
		sc := bufio.NewScanner(stream)
		for sc.Scan() {
			slog.Debug(sc.Text())
		}
		if err := sc.Err(); err != nil {
			slog.Error("failed to read stream", "error", err)
		}
	}

	wg.Add(2)
	go readStream(stdout)
	go readStream(stderr)
	wg.Wait()
}

func NewVMProcess(config *config.VMConfig) *VMProcess {
	apiPort := config.Port + 1
	macAddress := generateMacAddress()

	vp := &VMProcess{
		apiPort:        apiPort,
		circuitBreaker: circuitbreaker.NewCircuitBreaker(3, 10*time.Second),
		config:         config,
		ipDiscovery:    ipdiscovery.NewIPDiscovery(macAddress, ""),
		macAddress:     macAddress,
		pidFile:        filepath.Join(config.WorkingDirectory, "vfkit.pid"),
	}

	vp.apiClient = api.NewAPIClient(apiPort, vp.IsRunning)

	return vp
}

func (vp *VMProcess) IsRunning() bool {
	vp.mu.Lock()
	defer vp.mu.Unlock()
	return vp.command != nil && vp.command.ProcessState == nil
}

func (vp *VMProcess) IPAddress() string {
	vp.mu.Lock()
	defer vp.mu.Unlock()
	return vp.ipAddress
}

func (vp *VMProcess) buildVfkitCommand() []string {
	diffDiskPath := filepath.Join(vp.config.WorkingDirectory, diffDiskFileName)
	efiStorePath := filepath.Join(vp.config.WorkingDirectory, efiVariableStoreFileName)
	serialLogFilePath := "/dev/null"
	sshdKeysDirPath := filepath.Join(vp.config.WorkingDirectory, sshdKeysSharedDirName)

	if vp.config.Debug {
		serialLogFilePath = filepath.Join(vp.config.WorkingDirectory, serialLogFileName)
	}

	cmd := []string{
		vfkitBin,
		"--cpus",
		fmt.Sprintf("%d", vp.config.Cores),
		"--memory",
		fmt.Sprintf("%d", vp.config.Memory),
		"--bootloader",
		fmt.Sprintf("efi,variable-store=%s,create", efiStorePath),
		"--device",
		fmt.Sprintf("virtio-blk,path=%s", diffDiskPath),
		"--device",
		fmt.Sprintf("virtio-fs,sharedDir=%s,mountTag=sshd-keys", sshdKeysDirPath),
		"--device",
		fmt.Sprintf("virtio-net,nat,mac=%s", vp.macAddress),
		"--device",
		fmt.Sprintf("virtio-serial,logFilePath=%s", serialLogFilePath),
		"--restful-uri",
		fmt.Sprintf("tcp://localhost:%d", vp.apiPort),
		"--device",
		"virtio-rng",
		"--device",
		"virtio-balloon",
	}

	if vp.config.Rosetta {
		cmd = append(cmd, "--device", "rosetta,mountTag=rosetta")
	}

	for tag, path := range vp.config.SharedDirs {
		cmd = append(cmd, "--device", fmt.Sprintf("virtio-fs,sharedDir=%s,mountTag=%s", path, tag))
	}

	return cmd
}

func (vp *VMProcess) getStateInfoRaw() (api.Data, error) {
	return vp.apiClient.Get("/vm/state")
}

func (vp *VMProcess) getStateInfoWithBreaker() (api.Data, error) {
	var state api.Data

	err := vp.circuitBreaker.Call(func() error {
		var err error
		state, err = vp.getStateInfoRaw()
		return err
	})

	return state, err
}

func (vp *VMProcess) getStateInfo() (api.Data, error) {
	maxRetries := 3
	var finalErr error
	for attempt := range maxRetries {
		state, err := vp.apiClient.Get("/vm/state")
		if err == nil {
			return state, nil
		}

		finalErr = err

		if attempt < maxRetries-1 {
			jitter := time.Duration(mrand.Int64N(int64(100 * time.Millisecond)))
			time.Sleep(100*time.Millisecond*time.Duration(1<<attempt) + jitter)
		}
	}

	return nil, finalErr
}

func (vp *VMProcess) GetCurrentState() VMProcessState {
	if !vp.IsRunning() {
		return VMProcessStateStopped
	}

	stateInfo, err := vp.getStateInfoWithBreaker()
	if err != nil {
		if vp.IsRunning() {
			return VMProcessStateUnknown
		} else {
			return VMProcessStateStopped
		}
	}

	raw, ok := stateInfo["state"]
	if !ok {
		return VMProcessStateUnknown
	}

	state, ok := raw.(string)
	if !ok {
		return VMProcessStateUnknown
	}

	switch state {
	case string(api.VMStateRunning):
		return VMProcessStateRunning
	case string(api.VMStatePaused):
		return VMProcessStatePaused
	case string(api.VMStateStopped):
		return VMProcessStateStopped
	}

	return VMProcessStateUnknown
}

func (vp *VMProcess) canPause() bool {
	if !vp.IsRunning() {
		return false
	}

	stateInfo, err := vp.getStateInfo()
	if err != nil {
		return false
	}

	raw, ok := stateInfo["canPause"]
	if !ok {
		return false
	}

	canPause, ok := raw.(bool)
	if !ok {
		return false
	}

	return canPause
}

func (vp *VMProcess) canResume() bool {
	if !vp.IsRunning() {
		return false
	}

	stateInfo, err := vp.getStateInfo()
	if err != nil {
		return false
	}

	raw, ok := stateInfo["canResume"]
	if !ok {
		return false
	}

	canResume, ok := raw.(bool)
	if !ok {
		return false
	}

	return canResume
}

func (vp *VMProcess) removePIDFile() error {
	if err := os.Remove(vp.pidFile); err != nil {
		if os.IsNotExist(err) {
			return nil
		}

		return fmt.Errorf("failed to remove PID file: %w", err)
	}

	return nil
}

func (vp *VMProcess) writePIDFile() error {
	tmpFile, err := os.CreateTemp(vp.config.WorkingDirectory, "vfkit.pid.*")
	if err != nil {
		return fmt.Errorf("failed to create temporary PID file: %w", err)
	}

	committed := false
	tmpFilePath := tmpFile.Name()

	defer func() {
		tmpFile.Close()
		if !committed {
			os.Remove(tmpFilePath)
		}
	}()

	if _, err := fmt.Fprintf(tmpFile, "%d", vp.command.Process.Pid); err != nil {
		return fmt.Errorf("failed to write PID to temporary PID file: %w", err)
	}

	if err := tmpFile.Sync(); err != nil {
		return err
	}

	if err := os.Rename(tmpFilePath, vp.pidFile); err != nil {
		return err
	}

	committed = true
	return nil
}

func (vp *VMProcess) startVMProcess() error {
	if vp.IsRunning() {
		return fmt.Errorf("VM process is already running")
	}

	vfkitCommand := vp.buildVfkitCommand()
	cmd := exec.Command(vfkitCommand[0], vfkitCommand[1:]...)
	cmd.Dir = vp.config.WorkingDirectory

	var stdout, stderr io.ReadCloser
	if vp.config.Debug {
		var err error

		stdout, err = cmd.StdoutPipe()
		if err != nil {
			return err
		}

		stderr, err = cmd.StderrPipe()
		if err != nil {
			return err
		}
	} else {
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to execute command: %w", err)
	}

	vp.mu.Lock()
	vp.command = cmd
	vp.processExitCh = make(chan struct{})
	vp.mu.Unlock()

	if err := vp.writePIDFile(); err != nil {
		return err
	}

	if vp.config.Debug {
		outputCh := make(chan struct{})

		vp.mu.Lock()
		vp.outputCh = outputCh
		vp.mu.Unlock()

		go consumeVMProcessOutput(stdout, stderr, outputCh)
	}

	return nil
}

func (vp *VMProcess) monitorVM() {
	vp.mu.Lock()
	cmd := vp.command
	outputCh := vp.outputCh
	vp.mu.Unlock()

	if cmd == nil {
		return
	}

	if outputCh != nil {
		<-outputCh
	}

	err := cmd.Wait()

	vp.mu.Lock()
	exitCh := vp.processExitCh
	vp.mu.Unlock()

	if exitCh != nil {
		close(exitCh)
	}

	if err != nil && !vp.shutdownRequested.Load() {
		slog.Error("VM process died unexpectedly", "error", err)
	} else {
		slog.Info("VM shut down normally")
	}

	if !vp.shutdownRequested.Load() {
		vp.resetVMProcessState()
	}
}

func (vp *VMProcess) resetVMProcessState() {
	vp.mu.Lock()
	outputCh := vp.outputCh
	vp.command = nil
	vp.ipAddress = ""
	vp.outputCh = nil
	vp.processExitCh = nil
	vp.mu.Unlock()

	if outputCh != nil {
		<-outputCh
	}

	if vp.apiClient != nil {
		vp.apiClient.Close()
	}

	vp.removePIDFile()
	slog.Info("reset VM process state")
}

func (vp *VMProcess) getIPAddress() (string, error) {
	interval := 100 * time.Millisecond
	maxInterval := 2 * time.Second

	slog.Info("starting IP discovery")

	startTime := time.Now()
	for time.Since(startTime) < ipDiscoveryTimeout {
		if vp.shutdownRequested.Load() {
			return "", fmt.Errorf("failed to discover IP address: VM shutdown requested")
		}

		if !vp.IsRunning() {
			return "", fmt.Errorf("failed to discover IP address: VM process died")
		}

		ipAddress, err := vp.ipDiscovery.DiscoverIP()
		if err != nil {
			return "", fmt.Errorf("failed to discover IP address: %w", err)
		}

		if ipAddress != "" {
			vp.mu.Lock()
			vp.ipAddress = ipAddress
			vp.mu.Unlock()

			slog.Debug("IP address found", slog.String("ip_address", ipAddress))
			return ipAddress, nil
		}

		time.Sleep(interval)
		interval = min(interval*2, maxInterval)
	}

	return "", fmt.Errorf("failed to discover IP address: timeout exceeded")
}

func (vp *VMProcess) waitForSSH(ipAddress string, tester *ssh.SSHConnectivityTester) error {
	increment := 125 * time.Millisecond
	interval := 500 * time.Millisecond
	maxInterval := 1 * time.Second

	slog.Info("waiting for SSH connectivity to VM")

	startTime := time.Now()
	for time.Since(startTime) < sshReadyTimeout {
		ok, err := tester.TestConnectivity(ipAddress, 5)
		if err != nil {
			return fmt.Errorf("SSH connectivity test failed: %w", err)
		}

		if ok {
			return nil
		}

		time.Sleep(interval)
		interval = min(interval+increment, maxInterval)
	}

	return fmt.Errorf("SSH connectivity test failed: timeout exceeded")
}

func (vp *VMProcess) Start() error {
	slog.Info("starting the VM")

	vp.shutdownRequested.Store(false)

	if err := vp.killOrphanedVfkitProcesses(); err != nil {
		slog.Error("failed to kill orphaned vfkit process", "error", err)
	}
	if err := vp.startVMProcess(); err != nil {
		return err
	}

	go vp.monitorVM()

	sshTester := ssh.NewSSHConnectivityTester(vp.config.WorkingDirectory)

	ipAddress, err := vp.getIPAddress()
	if err != nil {
		vp.Stop(30 * time.Second)
		return err
	}

	if err := vp.waitForSSH(ipAddress, sshTester); err != nil {
		vp.Stop(30 * time.Second)
		return err
	}

	return nil
}

func (vp *VMProcess) Stop(timeout time.Duration) error {
	slog.Info("stopping the VM")

	vp.shutdownRequested.Store(true)

	vp.mu.Lock()
	cmd := vp.command
	exitCh := vp.processExitCh
	vp.mu.Unlock()

	if cmd != nil && exitCh != nil {
		cmd.Process.Signal(syscall.SIGTERM)

		select {
		case <-exitCh:
			slog.Info("VM stopped gracefully")
		case <-time.After(timeout):
			slog.Info("unable to stop VM gracefully, killing process instead", "reason", "timeout exceeded")
			cmd.Process.Kill()
			<-exitCh
		}
	}

	vp.resetVMProcessState()
	return nil
}

func (vp *VMProcess) Pause() error {
	slog.Info("pausing the VM")

	if !vp.IsRunning() {
		return fmt.Errorf("failed to pause VM: process is not running")
	}

	if ok := vp.canPause(); !ok {
		return fmt.Errorf("failed to pause VM: VM cannot be paused in it's current state")
	}

	_, err := vp.apiClient.Post("/vm/state", api.Data{"state": "Pause"})
	if err != nil {
		return fmt.Errorf("failed to pause VM: %w", err)
	}

	slog.Info("VM paused")
	return nil
}

func (vp *VMProcess) Resume() error {
	slog.Info("resuming the VM")

	if !vp.IsRunning() {
		return fmt.Errorf("failed to resume VM: process is not running")
	}

	if ok := vp.canResume(); !ok {
		return fmt.Errorf("failed to resume VM: VM cannot be resumed in it's current state")
	}

	_, err := vp.apiClient.Post("/vm/state", api.Data{"state": "Resume"})
	if err != nil {
		return fmt.Errorf("failed to resume VM: %w", err)
	}

	slog.Info("VM resumed")
	return nil
}

func (vp *VMProcess) PauseOrStop() error {
	if err := vp.Pause(); err == nil {
		return nil
	}
	slog.Info("VM cannot be paused, stopping instead")

	stopTimeout := 30 * time.Second
	if err := vp.Stop(stopTimeout); err != nil {
		return err
	}

	return nil
}

func (vp *VMProcess) ResumeOrStart() error {
	state := vp.GetCurrentState()

	switch state {
	case VMProcessStateRunning:
		return nil

	case VMProcessStatePaused:
		if err := vp.Resume(); err == nil {
			return nil
		}
		if err := vp.Stop(30 * time.Second); err != nil {
			return err
		}

	case VMProcessStateStopped:
		break

	case VMProcessStateUnknown:
		if err := vp.Stop(30 * time.Second); err != nil {
			return err
		}
	}

	if err := vp.Start(); err != nil {
		return err
	}

	return nil
}

func (vp *VMProcess) killOrphanedVfkitProcesses() error {
	content, err := os.ReadFile(vp.pidFile)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("failed to read PID file: %w", err)
	}

	procExists := func(pid int) bool {
		if err := syscall.Kill(pid, 0); err != nil && errors.Is(err, syscall.ESRCH) {
			return false
		}
		return true
	}

	defer os.Remove(vp.pidFile)

	pid, err := strconv.Atoi(strings.TrimSpace(string(content)))
	if err != nil || pid == 0 {
		return err
	}

	if !procExists(pid) {
		return nil
	}

	syscall.Kill(pid, syscall.SIGTERM)
	time.Sleep(500 * time.Millisecond)

	if !procExists(pid) {
		return nil
	}

	syscall.Kill(pid, syscall.SIGKILL)
	return nil
}
