package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

type vmConfigJSON struct {
	Cores                int               `json:"cores"`
	Debug                bool              `json:"debug"`
	Driver               string            `json:"driver"`
	DriverBin            string            `json:"driver-bin"`
	Memory               int               `json:"memory"`
	NestedVirtualization bool              `json:"nested-virtualization"`
	OnDemand             bool              `json:"on-demand"`
	Port                 int               `json:"port"`
	Rosetta              bool              `json:"rosetta"`
	SharedDirs           map[string]string `json:"shared-dirs"`
	TTL                  int               `json:"ttl"`
	VMNetHelperBin       string            `json:"vmnet-helper-bin"`
}

type VMConfig struct {
	Cores                int
	Debug                bool
	Driver               string
	DriverBin            string
	Memory               int
	NestedVirtualization bool
	OnDemand             bool
	Port                 int
	Rosetta              bool
	SharedDirs           map[string]string
	TTL                  int
	VMNetHelperBin       string
	WorkingDirectory     string
}

func NewVMConfig(configFilePath string) (*VMConfig, error) {
	f, err := os.Open(configFilePath)
	if err != nil {
		return nil, fmt.Errorf("failed to open config file: %w", err)
	}
	defer f.Close()

	raw := vmConfigJSON{TTL: 10800}
	if err := json.NewDecoder(f).Decode(&raw); err != nil {
		return nil, fmt.Errorf("invalid config JSON: %w", err)
	}

	if raw.Cores < 1 {
		return nil, fmt.Errorf("invalid value for 'cores': %v", raw.Cores)
	}
	if raw.Memory < 1024 {
		return nil, fmt.Errorf("invalid value for 'memory': %v", raw.Memory)
	}
	if raw.Port < 1024 || raw.Port > 65535 {
		return nil, fmt.Errorf("invalid value for 'port': %v", raw.Port)
	}

	if _, err := os.Stat(raw.DriverBin); err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("path not found: %s", raw.DriverBin)
		}
		return nil, fmt.Errorf("could not access path: %w", err)
	}

	resolvedSharedDirs := make(map[string]string)

	for tag, path := range raw.SharedDirs {
		info, err := os.Stat(path)
		if err != nil {
			if os.IsNotExist(err) {
				return nil, fmt.Errorf("path not found: %s", path)
			}
			return nil, fmt.Errorf("could not access path: %w", err)
		}
		if !info.IsDir() {
			return nil, fmt.Errorf("path is not a directory: %s", path)
		}

		absPath, err := filepath.Abs(path)
		if err != nil {
			return nil, fmt.Errorf("could not resolve path %s: %w", path, err)
		}

		resolvedSharedDirs[tag] = absPath
	}

	if raw.Driver == DriverKrunkit {
		if _, err := os.Stat(raw.VMNetHelperBin); err != nil {
			if os.IsNotExist(err) {
				return nil, fmt.Errorf("path not found: %s", raw.VMNetHelperBin)
			}
			return nil, fmt.Errorf("could not access path: %w", err)
		}
	}

	workingDirectory := os.Getenv("VIRBY_WORKING_DIRECTORY")
	if workingDirectory == "" {
		workingDirectory = WorkingDirectoryDefault
	}

	info, err := os.Stat(workingDirectory)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("path not found: %s", workingDirectory)
		}
		return nil, fmt.Errorf("could not access path: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("path is not a directory: %s", workingDirectory)
	}

	workingDirectoryAbs, err := filepath.Abs(workingDirectory)
	if err != nil {
		return nil, fmt.Errorf("could not resolve path %s: %w", workingDirectory, err)
	}

	return &VMConfig{
		Cores:                raw.Cores,
		Debug:                raw.Debug,
		Driver:               raw.Driver,
		DriverBin:            raw.DriverBin,
		Memory:               raw.Memory,
		NestedVirtualization: raw.NestedVirtualization,
		OnDemand:             raw.OnDemand,
		Port:                 raw.Port,
		Rosetta:              raw.Rosetta,
		SharedDirs:           resolvedSharedDirs,
		TTL:                  raw.TTL,
		VMNetHelperBin:       raw.VMNetHelperBin,
		WorkingDirectory:     workingDirectoryAbs,
	}, nil
}
