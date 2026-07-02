package vmnethelper

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

type VMNetHelper struct {
	command        *exec.Cmd
	exitCh         chan struct{}
	mu             sync.Mutex
	stopRequested  atomic.Bool
	vmnetHelperBin string
}

func NewVMNetHelper(vmnetHelperBin string) *VMNetHelper {
	return &VMNetHelper{vmnetHelperBin: vmnetHelperBin}
}

func (h *VMNetHelper) createSocketpair() (*os.File, *os.File, error) {
	fds, err := syscall.Socketpair(syscall.AF_UNIX, syscall.SOCK_DGRAM, 0)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create socketpair: %w", err)
	}

	bufSize := 256 * 1024
	for _, fd := range fds {
		if err := syscall.SetsockoptInt(fd, syscall.SOL_SOCKET, syscall.SO_SNDBUF, bufSize); err != nil {
			return nil, nil, fmt.Errorf("failed to set SO_SNDBUF: %w", err)
		}
		if err := syscall.SetsockoptInt(fd, syscall.SOL_SOCKET, syscall.SO_RCVBUF, bufSize); err != nil {
			return nil, nil, fmt.Errorf("failed to set SO_RCVBUF: %w", err)
		}
	}

	helperFD := os.NewFile(uintptr(fds[0]), "vmnet-helper-fd")
	driverFD := os.NewFile(uintptr(fds[1]), "vm-driver-fd")

	return helperFD, driverFD, nil
}

func (h *VMNetHelper) Start() (*os.File, error) {
	helperFD, driverFD, err := h.createSocketpair()
	if err != nil {
		return nil, err
	}

	args := []string{"--fd", "3", "--enable-checksum-offload", "--enable-tso"}

	cmd := exec.Command(h.vmnetHelperBin, args...)
	cmd.ExtraFiles = []*os.File{helperFD}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		driverFD.Close()
		helperFD.Close()
		return nil, err
	}

	slog.Info("starting vmnet-helper")
	h.stopRequested.Store(false)

	if err := cmd.Start(); err != nil {
		driverFD.Close()
		helperFD.Close()
		return nil, fmt.Errorf("failed to execute command: %w", err)
	}

	helperFD.Close()

	h.mu.Lock()
	h.command = cmd
	h.exitCh = make(chan struct{})
	h.mu.Unlock()

	go h.monitor()

	if err := json.NewDecoder(stdout).Decode(&json.RawMessage{}); err != nil {
		cmd.Process.Kill()
		<-h.exitCh
		driverFD.Close()

		return nil, fmt.Errorf("failed to decode vmnet-helper JSON output: %w", err)
	}

	return driverFD, nil
}

func (h *VMNetHelper) monitor() {
	h.mu.Lock()
	cmd := h.command
	h.mu.Unlock()

	if cmd == nil {
		return
	}

	err := cmd.Wait()

	h.mu.Lock()
	exitCh := h.exitCh
	h.mu.Unlock()

	if exitCh != nil {
		close(exitCh)
	}

	if err != nil && !h.stopRequested.Load() {
		slog.Error("vmnet-helper process failed", "error", err)
	}
}

func (h *VMNetHelper) Stop(timeout time.Duration) {
	slog.Info("stopping vmnet-helper")

	h.stopRequested.Store(true)

	h.mu.Lock()
	cmd := h.command
	exitCh := h.exitCh
	h.mu.Unlock()

	if cmd != nil && exitCh != nil {
		cmd.Process.Signal(syscall.SIGTERM)

		select {
		case <-exitCh:
			slog.Info("vmnet-helper stopped gracefully")
		case <-time.After(timeout):
			slog.Info("unable to stop vmnet-helper gracefully, killing process instead", "reason", "timeout exceeded")
			cmd.Process.Kill()
			<-exitCh
		}
	}

	h.mu.Lock()
	h.command = nil
	h.exitCh = nil
	h.mu.Unlock()
}
