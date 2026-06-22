package main

import (
	"log"
	"os"
	"vm-runner/internal/config"
	"vm-runner/internal/runner"
	"vm-runner/internal/signalmanager"
)

func run() int {
	log.SetFlags(log.LstdFlags)
	log.SetOutput(os.Stdout)

	configFilePath := os.Getenv("VIRBY_VM_CONFIG_FILE")
	cfg, err := config.NewVMConfig(configFilePath)
	if err != nil {
		log.Print(err)
		return 1
	}

	sm := signalmanager.NewSignalManager()
	sm.Setup()
	defer sm.Cleanup()

	r := runner.NewRunner(cfg, sm)
	if err := r.Run(); err != nil {
		log.Print(err)
		return 1
	}

	return 0
}

func main() {
	os.Exit(run())
}
