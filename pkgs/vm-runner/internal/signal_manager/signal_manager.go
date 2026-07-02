package signal_manager

import (
	"os"
	"os/signal"
	"sync"
	"syscall"
)

type SignalManager struct {
	handlers     []func()
	mu           sync.Mutex
	setupOnce    sync.Once
	shutdownCh   chan struct{}
	shutdownOnce sync.Once
}

func NewSignalManager() *SignalManager {
	return &SignalManager{
		shutdownCh: make(chan struct{}),
	}
}

func (s *SignalManager) IsShutdownRequested() bool {
	select {
	case <-s.shutdownCh:
		return true
	default:
		return false
	}
}

func (s *SignalManager) RequestShutdown() {
	s.shutdownOnce.Do(func() { close(s.shutdownCh) })
}

func (s *SignalManager) ShutdownCh() <-chan struct{} {
	return s.shutdownCh
}

func (s *SignalManager) AddShutdownHandler(fn func()) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.handlers = append(s.handlers, fn)
}

func (s *SignalManager) Setup() {
	s.setupOnce.Do(func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

		go func() {
			<-sigCh
			s.RequestShutdown()
			s.mu.Lock()
			hc := make([]func(), len(s.handlers))
			copy(hc, s.handlers)
			s.mu.Unlock()
			for _, h := range hc {
				h()
			}
		}()
	})
}

func (s *SignalManager) Cleanup() {
	signal.Reset(syscall.SIGTERM, syscall.SIGINT)
	s.mu.Lock()
	s.handlers = nil
	s.mu.Unlock()
}
