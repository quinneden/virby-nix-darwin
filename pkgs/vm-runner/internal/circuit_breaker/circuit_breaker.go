package circuit_breaker

import (
	"fmt"
	"sync"
	"time"
)

type CircuitState int

const (
	CircuitStateClosed CircuitState = iota
	CircuitStateHalfOpen
	CircuitStateOpen
)

type CircuitBreaker struct {
	failureCount     int
	failureThreshold int
	lastFailureTime  time.Time
	mu               sync.Mutex
	state            CircuitState
	timeout          time.Duration
}

func NewCircuitBreaker(failureThreshold int, timeout time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		failureThreshold: failureThreshold,
		timeout:          timeout,
	}
}

func (c *CircuitBreaker) Call(fn func() error) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state == CircuitStateOpen {
		if time.Since(c.lastFailureTime) > c.timeout {
			c.state = CircuitStateHalfOpen
		} else {
			return fmt.Errorf("circuit breaker is open")
		}
	}

	if err := fn(); err != nil {
		c.lastFailureTime = time.Now()
		c.failureCount++
		if c.failureCount >= c.failureThreshold {
			c.state = CircuitStateOpen
		}
		return err
	}

	c.failureCount = 0
	c.state = CircuitStateClosed
	return nil
}

func (c *CircuitBreaker) IsClosed() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.state == CircuitStateClosed
}

func (c *CircuitBreaker) IsHalfOpen() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.state == CircuitStateHalfOpen
}

func (c *CircuitBreaker) IsOpen() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.state == CircuitStateOpen
}

func (c *CircuitBreaker) Reset() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.failureCount = 0
	c.lastFailureTime = time.Time{}
	c.state = CircuitStateClosed
}
