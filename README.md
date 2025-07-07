# Virby - Linux Builder for Nix-darwin

Virby is a module for [nix-darwin](https://github.com/nix-darwin/nix-darwin) that configures a lightweight, [vfkit](https://github.com/crc-org/vfkit)-based linux VM as a remote build machine for nix, allowing linux packages to be built on macOS. This project is modeled after [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder), which provides a similar service, using lima to manage the VM. Some parts of the code in this repository are directly borrowed and adapted from that project.

## Quick Start

Add to your flake and enable:

```nix
# flake.nix
{
  inputs.virby = {
    url = "github:quinneden/virby-nix-darwin";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { virby, ... }: {
    darwinConfigurations."myHost" = {
      modules = [ virby.darwinModules.default ];
    };
  };
}
```

```nix
# configuration.nix
services.virby = {
  enable = true;
  cores = 8;
  memory = "6GiB";
  diskSize = "100GiB";
};
```

Then rebuild: `darwin-rebuild switch --flake .#myHost`

## Key Features

- **On-demand activation** - VM starts only when builds are needed, shuts down after inactivity
- **Rosetta support** - Build x86_64-linux packages on Apple Silicon using Rosetta translation
- **Secure by default** - Host-only access via loopback (i.e. `127.0.0.1`), with automatic ED25519 key generation
- **Fully configurable** - Adjust VM resources and add custom NixOS modules

## Configuration

### Basic Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | bool | `false` | Enable the service |
| `cores` | int | `8` | CPU cores allocated to VM |
| `memory` | int/string | `6144` | Memory in MiB or string format (e.g. "6GiB") |
| `diskSize` | string | `"100GiB"` | VM disk size |
| `port` | int | `31222` | SSH port for VM access |
| `speedFactor` | int | `1` | Speed factor for Nix build machine |

### Advanced Settings

**On-Demand Activation**
```nix
services.virby.onDemand = {
  enable = true;
  ttl = 180;  # Idle timeout in minutes
};
```

**Rosetta Support** (Apple Silicon only)
```nix
services.virby.rosetta.enable = true;
```

**Custom NixOS Configuration**
```nix
services.virby.extraConfig = {
  inherit (config.nix) settings;
  # Any valid NixOS configuration
};
```

**Debug Options** (insecure, for troubleshooting only)
```nix
services.virby = {
  debug = true;         # Enable verbose logging
  allowUserSsh = true;  # Allow non-root SSH access
};
```

> [!Note]
> Changes to `extraConfig` will cause the VM disk image and SSH keys to be recreated.

## Architecture

Virby integrates three components:

- **nix-darwin Module** - Configures VM as a Nix build machine for host
- **VM Image** - Minimal NixOS disk image configured for secure ssh access and build isolation
- **VM Runner** - Python package managing VM lifecycle and SSH proxying

**Build workflow:** Linux build requested → VM started (if needed) → Build executed in isolated environment → Results returned → VM shutdown (after idle timeout)

**Security model:** VM accessible only via localhost with key-based SSH authentication, minimal privileges, and filesystem isolation.

## Troubleshooting

**Debug logging:**
```nix
services.virby.debug = true;
```

```bash
# View daemon logs
tail -f /tmp/virbyd.stdout.log
```

**SSH into VM:**
```bash
# Requires allowUserSsh = true
ssh virby-vm
# or use sudo
```

## Acknowledgments

- Inspired by [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder)
- Powered by [vfkit](https://github.com/crc-org/vfkit) for native macOS virtualization

---

**License**: MIT - see LICENSE file for details.
