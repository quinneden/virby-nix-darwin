# Virby - Linux Builder for Nix-darwin

Virby is a module for [nix-darwin](https://github.com/nix-darwin/nix-darwin) that configures a lightweight, [vfkit](https://github.com/crc-org/vfkit)-based linux VM as a remote build machine for nix, allowing linux packages to be built on macOS. This project is modeled after [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder), which provides a similar service, using lima to manage the VM. Some parts of the code in this repository are directly borrowed and adapted from that project.

## Quick Start

Add virby to your flake inputs:

```nix
{
  inputs = {
    virby.url = "github:quinneden/virby-nix-darwin";
    # It is important that you dont add the line:
    # 
    #   inputs.nixpkgs.follows = "nixpkgs";
    #
    # until after you've activated with `darwin-rebuild`. This way, the cached
    # image can be used and you won't have to build from source (which requires
    # an existing aarch64-linux builder).
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

### Available Options

|Option|Type|Default|Description|
|-|-|-|-|
|`enable`|_bool_|`false`| Enable the service|
|`allowUserSsh`|_bool_|`false`|Allow non-root users to SSH into the VM|
|`cores`|_int_|`8`| CPU cores allocated to VM|
|`debug`|_bool_|`false`|Enable debug logging for the VM|
|`diskSize`|_string_|`"100GiB"`| VM disk size|
|`extraConfig`|_module_|`{}`|Additional NixOS modules to include in the VM's system configuration|
|`memory`|_int_ or _string_|`6144`| Memory in MiB or string format (e.g. "6GiB")|
|`onDemand.enable`|_bool_|`false`|Enable on-demand activation of the VM|
|`onDemand.ttl`|_int_|`180`|The number of minutes of inactivity which must pass before the VM shuts down|
|`port`|_int_|`31222`| SSH port for VM access|
|`rosetta`|_bool_|`true`|Enable Rosetta support for the VM|
|`sharedDirectories`|_attrs of string_|`{}`|An attribute set of directories that will be shared with the VM as virtio-fs devices|
|`speedFactor`|_int_|`1`| Speed factor for Nix build machine|
|`supportDeterminateNix`|_bool_|`false`|Enable support for using Virby with Determinate Nix|


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

> [!Warning]
> This option allows you to arbitrarily change the NixOS configuration, which could expose the VM to security risks.

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

**Debug Options** (insecure, for troubleshooting only)

```nix
{
  services.virby.debug = true;         # Enable verbose logging
  services.virby.allowUserSsh = true;  # Allow non-root SSH access with a separate shared key copy
}
```

## Architecture

Virby integrates three components:

- **nix-darwin Module** - Configures VM as a Nix build machine for host
- **VM Image** - Minimal NixOS disk image configured for secure ssh access and build isolation
- **VM Runner** - Go package managing VM lifecycle and SSH proxying

**Security model:**
- VM doesn't accept remote connections as it binds to the loopback interface
- SSH keys are generated and copied to the VM on first run.
- `builder` user has minimal permissions, root access is restricted by default

## Troubleshooting

**Debug logging**
```nix
{
  # Enable debug logging to `/tmp/virbyd.log`
  services.virby.debug = true;
}
```

```bash
# View daemon logs
tail -f /tmp/virbyd.log
```

**SSH into VM**

```bash
# Requires `allowUserSsh = true`
ssh virby-vm
# or use sudo
```

## Acknowledgments

- Inspired by [nix-rosetta-builder](https://github.com/cpick/nix-rosetta-builder)
- Uses [vfkit](https://github.com/crc-org/vfkit)

---

**License**: MIT - see [LICENSE](LICENSE) file for details.
