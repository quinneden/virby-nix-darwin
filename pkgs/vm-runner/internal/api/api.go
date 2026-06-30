package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"time"
)

type Data map[string]any
type VMState string

const (
	VMStateError     VMState = "VirtualMachineStateError"
	VMStatePaused    VMState = "VirtualMachineStatePaused"
	VMStatePausing   VMState = "VirtualMachineStatePausing"
	VMStateRestoring VMState = "VirtualMachineStateRestoring"
	VMStateResuming  VMState = "VirtualMachineStateResuming"
	VMStateRunning   VMState = "VirtualMachineStateRunning"
	VMStateSaving    VMState = "VirtualMachineStateSaving"
	VMStateStarting  VMState = "VirtualMachineStateStarting"
	VMStateStopped   VMState = "VirtualMachineStateStopped"
	VMStateStopping  VMState = "VirtualMachineStateStopping"
)

type APIClient struct {
	port           int
	isRunningCheck func() bool
	client         *http.Client
}

func NewAPIClient(port int, isRunningCheck func() bool) *APIClient {
	client := &http.Client{
		Timeout: 5 * time.Second,
		Transport: &http.Transport{
			MaxConnsPerHost: 5,
			MaxIdleConns:    2,
		},
	}

	return &APIClient{
		port:           port,
		isRunningCheck: isRunningCheck,
		client:         client,
	}
}

func (c *APIClient) callAPI(endpoint string, method string, data Data) (Data, error) {
	if c.isRunningCheck != nil && !c.isRunningCheck() {
		return nil, fmt.Errorf("the virtual machine is not running")
	}

	url := fmt.Sprintf("http://localhost:%d%s", c.port, endpoint)

	var bodyBytes []byte
	if data != nil {
		var err error
		bodyBytes, err = json.Marshal(data)
		if err != nil {
			return nil, fmt.Errorf("failed to encode request body: %w", err)
		}
	}

	maxRetries := 2
	for attempt := 0; attempt <= maxRetries; attempt++ {
		var body io.Reader
		if bodyBytes != nil {
			body = bytes.NewReader(bodyBytes)
		}

		req, err := http.NewRequest(method, url, body)
		if err != nil {
			return nil, fmt.Errorf("failed to create request: %w", err)
		}
		if data != nil {
			req.Header.Set("Content-Type", "application/json")
		}

		resp, err := c.client.Do(req)
		if err != nil {
			if attempt == maxRetries {
				return nil, err
			}

			jitter := time.Duration(rand.Int63n(int64(100 * time.Millisecond)))
			time.Sleep(100*time.Millisecond*time.Duration(1<<attempt) + jitter)
			continue
		}
		defer resp.Body.Close()

		if resp.StatusCode >= 400 {
			return nil, fmt.Errorf("request failed with status %d", resp.StatusCode)
		}

		respBody, err := io.ReadAll(resp.Body)
		if err != nil || len(respBody) == 0 {
			return nil, nil
		}

		var result Data
		if err := json.Unmarshal(respBody, &result); err != nil {
			return nil, nil
		}
		return result, nil
	}

	return nil, fmt.Errorf("request failed after %d attempts", maxRetries+1)
}

func (c *APIClient) Close() {
	c.client.CloseIdleConnections()
	c.client = nil
}

func (c *APIClient) Get(endpoint string) (Data, error) {
	return c.callAPI(endpoint, "GET", nil)
}

func (c *APIClient) Post(endpoint string, data Data) (Data, error) {
	return c.callAPI(endpoint, "POST", data)
}
