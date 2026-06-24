package main

import (
	"log/slog"
	"os"
	"vm-runner/internal/config"
	"vm-runner/internal/runner"
	"vm-runner/internal/signalmanager"
)

func setupLogging(debug bool) {
	logLevel := slog.LevelInfo
	if debug {
		logLevel = slog.LevelDebug
	}

	handler := slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: logLevel})
	logger := slog.New(handler)

	slog.SetDefault(logger)
}

func run() int {
	configFilePath := os.Getenv("VIRBY_VM_CONFIG_FILE")
	cfg, err := config.NewVMConfig(configFilePath)
	if err != nil {
		slog.Error("failed to get VM config", "error", err)
		return 1
	}

	setupLogging(cfg.Debug)

	sm := signalmanager.NewSignalManager()
	sm.Setup()
	defer sm.Cleanup()

	r := runner.NewRunner(cfg, sm)
	if err := r.Run(); err != nil {
		slog.Error(err.Error())
		return 1
	}

	return 0
}

func main() {
	os.Exit(run())
}
