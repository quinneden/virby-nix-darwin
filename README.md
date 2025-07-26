# Virby - Linux Builder for Nix-darwin

Virby is a module for [nix-darwin](https://github.com/nix-darwin/nix-darwin) that configures a lightweight, [vfkit](https://github.com/crc-org/vfkit)-based linux VM as a remote build machine for nix, allowing linux packages to be built on macOS. This project is modeled after [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder), which provides a similar service, using lima to manage the VM. Some parts of the code in this repository are directly borrowed and adapted from that project.

## Quick Start

Add virby to your flake inputs:

```nix
{
  inputs.virby = {
    url = "github:quinneden/virby-nix-darwin";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { virby, ... }: {
    darwinConfigurations."myHost" = {
      # Import the module
      modules = [ virby.darwinModules.default ];
    };
  };
}
```

> [!Important]
> When enabling Virby for the first time, you must add the binary cache to your Nix configuration. This ensures that the prebuilt VM image is available for download, rather than having to be built locally, which requires an existing linux builder. You can do this in one of two ways:

Add the binary cache to your configuration **before** enabling Virby:

```nix
{
  nix.settings.extra-substituters = [ "https://virby-nix-darwin.cachix.org" ];
  nix.settings.extra-trusted-public-keys = [
    "virby-nix-darwin.cachix.org-1:z9GiEZeBU5bEeoDQjyfHPMGPBaIQJOOvYOOjGMKIlLo="
  ];
  
  services.virby.enable = false;
}
```

Run `darwin-rebuild`, then enable Virby:

```nix
{
  nix.settings.extra-substituters = [ "https://virby-nix-darwin.cachix.org" ];
  nix.settings.extra-trusted-public-keys = [
    "virby-nix-darwin.cachix.org-1:z9GiEZeBU5bEeoDQjyfHPMGPBaIQJOOvYOOjGMKIlLo="
  ];
  
  # Don't configure any other Virby options until after you've switched to the new
  # configuration. If the hash for the disk image derivation doesn't match the one
  # in the binary cache, then nix will try to build the image locally.
  services.virby.enable = true;
}
```

Finally, rebuild again.

**OR**

Run the `darwin-rebuild` command with the following options:

```bash
sudo darwin-rebuild switch --flake .#myHost \
  --option "extra-substituters" "https://virby-nix-darwin.cachix.org" \
  --option "extra-trusted-public-keys" "virby-nix-darwin.cachix.org-1:z9GiEZeBU5bEeoDQjyfHPMGPBaIQJOOvYOOjGMKIlLo="
```

If you prefer building the image locally, you can enable the `nix.linux-builder` option before enabling Virby:

```nix
{
  nix.linux-builder.enable = true;

  services.virby.enable = false;
}
```

## Key Features

- **On-demand activation** (optional) - VM is started when needed, then shuts down after a period of inactivity
- **Rosetta support** (optional) - Build `x86_64-linux` packages on Apple Silicon using Rosetta translation
- **Secure by default** - Host-only access via loopback (i.e. `127.0.0.1`), with automatic ED25519 key generation
- **Fully configurable** - Adjust VM resources and add custom NixOS modules

## Configuration

### Basic Settings

| Option        | Type       | Default    | Description                                  |
|---------------|------------|------------|----------------------------------------------|
| `enable`      | bool       | `false`    | Enable the service                           |
| `cores`       | int        | `8`        | CPU cores allocated to VM                    |
| `memory`      | int/string | `6144`     | Memory in MiB or string format (e.g. "6GiB") |
| `diskSize`    | string     | `"100GiB"` | VM disk size                                 |
| `port`        | int        | `31222`    | SSH port for VM access                       |
| `speedFactor` | int        | `1`        | Speed factor for Nix build machine           |

### Other Settings

**On-demand Activation**

```nix
{
  services.virby.onDemand.enable = true;
  services.virby.onDemand.ttl = 180;  # Idle timeout in minutes
}
```

**Rosetta Support**

```nix
# Requires `aarch64-darwin` host
{
  services.virby.rosetta = true;
}
```

**Custom NixOS Configuration**


```nix
{
  services.virby.extraConfig = {
    inherit (config.nix) settings;
    # Some NixOS options which are defined in the default VM configuration cannot
    # be overridden, such as `networking.hostName`. Others may be overridden with
    # `lib.mkForce`. Also note that anything changed here will cause a rebuild of
    # the VM image, and SSH keys will be regenerated.
  };
}
```
> [!Warning]
> This option allows you to arbitrarily change the NixOS configuration, which could expose the VM to security risks.

**Debug Options** (insecure, for troubleshooting only)

```nix
{
  services.virby.debug = true;         # Enable verbose logging
  services.virby.allowUserSsh = true;  # Allow non-root SSH access
}
```

## Architecture

Virby integrates three components:

- **nix-darwin Module** - Configures VM as a Nix build machine for host
- **VM Image** - Minimal NixOS disk image configured for secure ssh access and build isolation
- **VM Runner** - Python package managing VM lifecycle and SSH proxying

**Build workflow:** Linux build requested → VM started (if needed) → Build on VM → Results copied to host → VM shutdown (after idle timeout)

**Security model:**
- VM doesn't accept remote connections as it binds to the loopback interface
- SSH keys are generated and copied to the VM on first run.
- `builder` user has minimal permissions, root access is restricted by default

## Benchmarks

| Test | Mean [s] | Min [s] | Max [s] | Relative |
|:---|---:|---:|---:|---:|
| Boot (cold start) | 9.203 ± 0.703 | 7.795 | 9.818 | 1.00 |
| Build (`nix build --no-link --rebuild nixpkgs#hello`) | 8.136 ± 0.031 | 8.087 | 8.173 | 1.00 |

## Troubleshooting

**Debug logging**
```nix
{
  services.virby.debug = true;
}
```

```bash
# View daemon logs
tail -f /tmp/virbyd.log
```

**SSH into VM**

```bash
# Requires allowUserSsh = true
ssh virby-vm
# or use sudo
```

## Acknowledgments

- Inspired by [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder)
- Uses [vfkit](https://github.com/crc-org/vfkit)

---

**License**: MIT - see [LICENSE](LICENSE) file for details.
