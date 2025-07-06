# Virby - A vfkit-based Linux Builder for Nix-darwin

Virby is a module for nix-darwin that configures a lightweight linux VM as a remote build machine for nix, allowing linux packages to be built on macOS. This project is modeled after [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder), which provides a similar service, using [lima](https://lima-vm.io) to manage the VM. Some parts of the code in this repository are directly borrowed and adapted from that project, such as the SSH key generation logic.

## Features

- **On-Demand Activation**: Optional socket activation for starting the VM only when needed
- **Rosetta Support**: Build x86_64-linux packages on Apple Silicon using Rosetta translation
- **Secure by Default**: VM is exposed only on the loopback interface (i.e. `127.0.0.1`) and only accessible via key-based authentication
- **Configurable Resources**: Configurable VM parameters and arbitrary NixOS modules

## Architecture

Virby consists of three main components:

1. **nix-darwin Module** (`modules/virby`) - Provides system integration and configuration
2. **VM Image** (`pkgs/vm-image`) - A minimal NixOS image, configured for use as a remote builder.
3. **VM Runner** (`pkgs/vm-runner`) - Python package that wraps `vfkit` and manages the VM lifecycle and SSH proxying.

## Installation

### Using Flakes

Add Virby to your flake inputs:

```nix
{
  inputs = {
    virby = {
      url = "github:quinneden/virby-nix-darwin";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # Import the module
  outputs =
    { virby, ... }:
    {
      darwinConfigurations."myHost" = {
        modules = [ virby.darwinModules.default ];
      };
    };
}
```
 
## Configuration

### Basic Configuration

```nix
services.virby = {
  enable = true;
  cores = 8;            # CPU cores for the VM
  memory = 6144;        # Memory allocation in MiB (can be int or string like: `"6GiB"`)
  diskSize = "100GiB";  # Disk size in GiB
};
```

### On Demand Activation with Port Forwarding

Enable on-demand VM activation with automatic SSH port forwarding:

```nix
services.virby = {
  onDemand = {
    enable = true;
    ttl = 180;  # Idle timeout in minutes
  };
};
```

When `onDemand.enable` is true, Virby implements socket activation with TCP port forwarding:

- **On-demand VM Startup**: The VM starts only when an SSH connection is received on the configured host port (`31222` by default)
- **TCP Proxy**: All traffic is transparently forwarded between the host port and the VM's SSH service
- **Resource Efficiency**: VM consumes no resources when not in use
- **Automatic VM Shutdown**: VM shuts down after the specified idle timeout (`onDemand.ttl`)

### Rosetta Support

> [!NOTE]
> This option is only available on `aarch64-darwin` systems.

Enable x86_64-linux builds using Rosetta:

```nix
services.virby = {
  rosetta.enable = true;
};
```

### Additional NixOS configuration modules

> [!NOTE]
> This option allows you to specify additional arbitrary NixOS module configuration. Any changes to this option's value will cause the VM's disk image and SSH keys to be recreated.

```nix
services.virby = {
  extraConfig = {
    nix.settings = config.nix.settings;
  };
};
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | bool | `false` | Enable the Virby service |
| `cores` | int | `8` | Number of CPU cores |
| `memory` | int \| string | `6144` | Memory in MiB or string like "6GiB" |
| `diskSize` | string | `"100GiB"` | VM disk size |
| `port` | int | `31222` | SSH port for VM access |
| `speedFactor` | int | `1` | Build speed factor for Nix |
| `allowUserSsh` | bool | `false` | Allow SSH access to the VM for non-root users on the host system. (for debugging only, insecure) |
| `debug` | bool | `false` | Enable VM serial and daemon output logging. (for debugging only, insecure) |
| `onDemand.enable` | bool | `false` | Enable on-demand VM activation |
| `onDemand.ttl` | int | `180` | VM idle timeout in minutes |
| `rosetta.enable` | bool | `false` | Enable Rosetta support (aarch64-darwin only) |
| `extraConfig` | attrs | `{}` | Additional NixOS configuration for VM |

## How It Works

1. **Image Creation**: Nix builds a minimal raw-efi NixOS disk image
2. **Key Generation**: SSH keys are automatically generated and copied to the VM on first boot
3. **VM Startup**: The Launchd daemon starts the VM (either at load or on-demand)
4. **IP Discovery**: VM's IP address is discovered via DHCP lease parsing
5. **Port Forwarding**: In on-demand mode, launchd socket activation triggers VM startup and TCP proxy
6. **Build Integration**: The Nix-darwin module configures the VM as a build machine, routing Linux builds to the VM
7. **Lifecycle Management**: VM can be kept running or managed on-demand with automatic shutdown after a period of inactivity

## Security

Virby is designed with security in mind:

- VM is only accessible from the host via the loopback interface (i.e. `127.0.0.1`)
- SSH uses ED25519 key-based authentication
- VM user has minimal privileges for building only
- Host keys are protected using virtiofs mount/unmount on first boot
- VM is isolated from the host filesystem

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- **Heavily** inspired by [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder).
- Uses [vfkit](https://github.com/crc-org/vfkit) for native macOS virtualization
