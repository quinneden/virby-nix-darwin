# Virby - A vfkit-based Linux Builder for Nix-darwin

Virby is a module for nix-darwin that configures a lightweight linux VM as a remote build machine for nix, allowing linux packages to be built on macOS. This project is modeled after [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder), which provides a similar service, using [lima](https://lima-vm.io) to manage the VM. Some parts of the code in this repository are directly borrowed and adapted from that project, such as the SSH key generation logic.

## Features

- **Seamless Integration**: Automatically integrates with nix-darwin's build system
- **On-Demand Activation**: Optional VM lifecycle management with automatic startup/shutdown
- **Rosetta Support**: Build x86_64-linux packages on Apple Silicon using Rosetta translation
- **Secure by Default**: VM is locked down and only accessible via SSH with generated keys
- **Configurable Resources**: Adjust CPU cores, memory, and disk size to your needs
- **Debug Support**: Optional logging and serial console access for troubleshooting

## Architecture

Virby consists of three main components:

1. **nix-darwin Module** (`modules/virby`) - Provides system integration and configuration
2. **VM Image** (`pkgs/vm-image`) - A minimal NixOS image, configured for use as a remote builder.
3. **VM Runner** (`pkgs/vm-runner`) - Python package that wraps `vfkit` and manages the VM lifecycle and IP discovery.

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

  # Add the module to your nix-darwin configuration
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
  memory = 6144;        # Memory allocation in MiB (can be int or string like: "6GiB")
  diskSize = "100GiB";  # Disk size in GiB
};
```

### On Demand Activation

Enable on-demand VM activation:

```nix
services.virby = {
  onDemand = {
    enable = true;
    ttl = 180;  # Idle timeout in minutes
  };
};
```

### Rosetta Support

> [!NOTE]
> This option is only available on `aarch64-darwin` systems.

Enable x86_64-linux builds using Rosetta:

```nix
services.virby = {
  rosetta.enable = true;
};
```

### Additional NixOS module configuration

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

1. **VM Creation**: Virby builds a minimal NixOS image optimized for building
2. **Key Generation**: SSH keys are automatically generated for secure access
3. **VM Startup**: The VM runner daemon starts the VM using vfkit
4. **IP Discovery**: VM's IP address is discovered via DHCP lease parsing
5. **Build Integration**: Nix automatically routes Linux builds to the VM
6. **Lifecycle Management**: VM can be kept running or managed on-demand

## Security

Virby is designed with security in mind:

- VM has no network access except through the host
- SSH access uses generated ED25519 keys
- VM user has minimal privileges for building only
- Host keys are protected using virtiofs mount/unmount
- VM is isolated from the host filesystem

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- **Heavily** inspired by [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder).
- Uses [vfkit](https://github.com/crc-org/vfkit) for native macOS virtualization
