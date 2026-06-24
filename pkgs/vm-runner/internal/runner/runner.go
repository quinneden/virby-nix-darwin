package runner

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"
	"vm-runner/internal/config"
	"vm-runner/internal/signalmanager"
	"vm-runner/internal/socketactivation"
	"vm-runner/internal/vmprocess"
)

type Runner struct {
	activationSocket    net.Listener
	activeConnections   atomic.Int32
	config              *config.VMConfig
	lastConnectionTime  time.Time
	mu                  sync.Mutex
	shutdownRequested   atomic.Bool
	shutdownTimerCancel context.CancelFunc
	signalManager       *signalmanager.SignalManager
	socketActivation    *socketactivation.SocketActivation
	vmProcess           *vmprocess.VMProcess
}

func NewRunner(config *config.VMConfig, signalManager *signalmanager.SignalManager) *Runner {
	return &Runner{
		config:           config,
		signalManager:    signalManager,
		socketActivation: socketactivation.NewSocketActivation(config.Debug, config.Port),
		vmProcess:        vmprocess.NewVMProcess(config),
	}
}

func (r *Runner) ensureVMReady() error {
	if r.signalManager.IsShutdownRequested() {
		return fmt.Errorf("shutdown requested, not starting VM")
	}

	if r.config.OnDemand {
		if err := r.vmProcess.ResumeOrStart(); err != nil {
			return err
		}
	} else if !r.vmProcess.IsRunning() {
		if err := r.vmProcess.Start(); err != nil {
			return err
		}
	}

	return nil
}

func (r *Runner) scheduleShutdownCheck(ctx context.Context) error {
	ttl := time.Duration(r.config.TTL) * time.Second
	timer := time.NewTimer(ttl)
	defer timer.Stop()

	slog.Info("scheduled shutdown check", slog.Int("seconds", r.config.TTL))

	select {
	case <-timer.C:
		if r.activeConnections.Load() == 0 {
			if r.config.OnDemand {
				if err := r.vmProcess.PauseOrStop(); err != nil {
					return err
				}
			} else {
				if err := r.vmProcess.Stop(30 * time.Second); err != nil {
					return err
				}
			}
		}
		return nil
	case <-ctx.Done():
		return nil
	}
}

func (r *Runner) proxyConnection(clientConn net.Conn) {
	active := r.activeConnections.Add(1)
	slog.Info("new connection", slog.Int("active_connections", int(active)))

	r.mu.Lock()
	r.lastConnectionTime = time.Now()
	if r.shutdownTimerCancel != nil {
		r.shutdownTimerCancel()
		r.shutdownTimerCancel = nil
	}
	r.mu.Unlock()

	defer func() {
		active = r.activeConnections.Add(-1)
		clientConn.Close()
		slog.Info("connection closed", slog.Int("active_connections", int(active)))
		if r.config.OnDemand {
			ctx, cancelCtx := context.WithCancel(context.Background())
			r.mu.Lock()
			r.shutdownTimerCancel = cancelCtx
			r.mu.Unlock()
			go r.scheduleShutdownCheck(ctx)
		}
	}()

	if r.shutdownRequested.Load() || r.signalManager.IsShutdownRequested() {
		slog.Info("shutdown requested, rejecting connection")
		return
	}

	if err := r.ensureVMReady(); err != nil {
		slog.Error("VM readiness check failed", "error", err)
		return
	}

	hostPort := net.JoinHostPort(r.vmProcess.IPAddress(), "22")
	vmConn, err := net.Dial("tcp", hostPort)
	if err != nil {
		slog.Error("failed to connect to VM", "error", err)
		return
	}

	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		io.Copy(clientConn, vmConn)
		if c, ok := clientConn.(interface{ CloseWrite() error }); ok {
			c.CloseWrite()
		}
	}()

	go func() {
		defer wg.Done()
		io.Copy(vmConn, clientConn)
		if c, ok := vmConn.(interface{ CloseWrite() error }); ok {
			c.CloseWrite()
		}
	}()

	wg.Wait()
	vmConn.Close()
}

func (r *Runner) handleActivationConnections() error {
	if r.activationSocket == nil {
		return fmt.Errorf("no activation socket available")
	}

	for {
		conn, err := r.activationSocket.Accept()
		if err != nil {
			if r.signalManager.IsShutdownRequested() {
				slog.Info("stopping connection handler", "reason", "shutdown requested")
				return nil
			}
			slog.Error("failed handling client connection", "error", err)
		} else {
			go r.proxyConnection(conn)
		}
	}
}

func (r *Runner) Run() error {
	defer r.vmProcess.Stop(30 * time.Second)

	if r.signalManager.IsShutdownRequested() {
		slog.Info("stopping signal manager", "reason", "shutdown requested")
		return nil
	}

	var err error
	r.activationSocket, err = r.socketActivation.GetActivationSocket()
	if err != nil {
		return fmt.Errorf("failed to get activation socket: %w", err)
	}

	if !r.config.OnDemand {
		if err := r.vmProcess.Start(); err != nil {
			return err
		}
	}

	connCh := make(chan error, 1)
	go func() { connCh <- r.handleActivationConnections() }()

	defer func() {
		r.shutdownRequested.Store(true)
		r.mu.Lock()
		if r.shutdownTimerCancel != nil {
			r.shutdownTimerCancel()
			r.shutdownTimerCancel = nil
		}
		r.mu.Unlock()
	}()

	select {
	case <-r.signalManager.ShutdownCh():
		r.activationSocket.Close()
		<-connCh
	case err := <-connCh:
		r.activationSocket.Close()
		if err != nil {
			return err
		}
	}

	return nil
}
