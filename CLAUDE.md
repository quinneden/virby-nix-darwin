# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Python Development (vm-runner package)
All Python development commands use `just` from the `pkgs/vm-runner` directory:

```bash
# Format code
just format

# Run linting checks  
just lint

# Run type checking
just type-check

# Run both lint and type check
just check

# Build the Python package
just build

# Clean build artifacts
just clean
```

### Nix Development

```bash
# Build the vm-runner package for Darwin
nix build .#packages.aarch64-darwin.vm-runner

# Build the vm-image for Linux
nix build .#packages.aarch64-linux.vm-image

# Run benchmarks
nix run .#benchmark-vm -- boot
nix run .#benchmark-vm -- build [derivation]

# Bump version (currently, only implemented for 'vm-runner' package)
nix run .#bump-version [package]
```

## Architecture Overview

Virby is a nix-darwin module that provides Linux build capabilities on macOS through three integrated components:

### 1. Nix-darwin Module (`module/`)
- Configures VM as a Nix build machine for the host
- Manages launchd daemon (`virbyd`) that runs the VM runner
- Sets up SSH configuration and keys for secure VM access
- Integrates with Nix's distributed builds system

### 2. VM Image (`pkgs/vm-image/`)
- Minimal NixOS disk image optimized for build isolation
- Configured for secure SSH access with generated ED25519 keys
- Built using `nixosSystem` with custom image configuration

### 3. VM Runner (`pkgs/vm-runner/`)
- Python package managing VM lifecycle and SSH proxying
- Handles on-demand VM startup/shutdown with configurable TTL
- Provides socket activation for seamless connection handling
- Supports both persistent and on-demand operation modes

### Key Components

- **VMProcess** (`vm_process.py`): Manages vfkit VM lifecycle (start/stop/pause/resume)
- **SocketActivation** (`socket_activation.py`): Handles launchd socket activation
- **VirbyVMRunner** (`runner.py`): Main orchestrator integrating all components
- **SignalManager** (`signal_manager.py`): Manages graceful shutdown signals

### Build Workflow
1. Linux build requested → VM started (if needed) 
2. Build executed on VM via SSH 
3. Results copied to host
4. VM shutdown after idle timeout (on-demand mode)

### Security Model
- VM binds only to loopback interface (127.0.0.1)
- Automatic ED25519 SSH key generation per VM image
- Restricted `builder` user with minimal permissions
- Host-only access prevents external connections

## Project Structure

- `flake.nix` - Main Nix flake defining packages and modules
- `module/` - nix-darwin module implementation
- `pkgs/vm-runner/` - Python VM runner package
- `pkgs/vm-image/` - NixOS VM image configuration
- `lib/` - Shared Nix libraries and helpers
- `scripts/` - Utility scripts (benchmarking, version bumping)
- `Justfile` - Task runner for Python development commands

## Configuration

The module is configured through `services.virby.*` options in nix-darwin. Key settings include:
- `enable` - Enable/disable the service
- `cores`, `memory`, `diskSize` - VM resource allocation
- `onDemand.enable` - On-demand activation mode
- `rosetta` - x86_64 emulation support on Apple Silicon
- `debug` - Enable verbose logging to `/tmp/virbyd.log`
