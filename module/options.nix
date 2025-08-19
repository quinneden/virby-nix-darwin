{ lib, ... }:
{
  options.services.virby = {
    enable = lib.mkEnableOption "Virby, a vfkit-based linux builder for nix-darwin";

    allowUserSsh = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Whether to allow non-root users to SSH into the VM.

        This is useful for debugging, but it means that any user on the host machine can ssh into
        the VM without root privileges, which could pose a security risk.
      '';
    };

    cores = lib.mkOption {
      type = lib.types.int;
      default = 8;
      description = ''
        The number of CPU cores allocated to the VM.

        This also sets the `nix.buildMachines.max-jobs` setting.
      '';
    };

    debug = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Whether to enable debug logging for the VM.

        When enabled, the launchd daemon will direct all stdout/stderr output to log files, as well
        as the VM's serial output. This is useful for debugging issues with the VM, but it may pose
        a security risk and should only be enabled when necessary.
      '';
    };

    diskSize = lib.mkOption {
      type = lib.types.str;
      default = "100GiB";
      description = ''
        The size of the disk image for the VM.

        The option value must be a string with a number, followed by the suffix "GiB".
      '';
    };

    extraConfig = lib.mkOption {
      type = lib.types.deferredModule;
      default = { };
      description = ''
        Additional NixOS modules to include in the VM's system configuration.

        The VM's default configuration allows it to be securely used as a builder. Be aware when
        using this option, that additional configuration could potentially expose the VM to
        security risks such as compromised derivations being added to the nix store.

        Any changes made to this option's value will cause a rebuild of the VM's disk image, and
        the copy-on-write overlay image will be recreated from the new base image.

        Options defined here which are also defined by the default configuration, but not forced in
        the default configuration, will override the default values. Some options in the default
        configuration are forced (with `lib.mkForce`), such as `networking.hostName`. Any options
        defined here which are forced in the default configuration will be silently ignored.
      '';
    };

    memory = lib.mkOption {
      type = with lib.types; either int str;
      default = 6144;
      description = ''
        The amount of memory to allocate to the VM in MiB.

        This can be specified as either: an integer representing an amount in MiB, e.g., `6144`, or
        a string, e.g., `"6GiB"`.
      '';
    };

    onDemand = lib.mkOption {
      type =
        with lib.types;
        (submodule {
          options = {
            enable = lib.mkOption {
              type = bool;
              default = false;
              description = ''
                Whether to enable on-demand activation of the VM.
              '';
            };
            ttl = lib.mkOption {
              type = int;
              default = 180;
              description = ''
                This specifies the number of minutes of inactivity which must pass before the VM
                shuts down.

                This option is only relevant when `onDemand.enable` is true.
              '';
            };
          };
        });
      default = { };
      description = ''
        By default, the VM is always-on, running as a daemon in the background. This allows builds
        to started right away, but also means the VM will always be consuming (a small amount of)
        cpu and memory resources.

        When enabled, this option will allow the VM to be activated on-demand; when not in use, the
        VM will not be running. When a build job requiring use of the VM is initiated, it signals
        the VM to start, and once an SSH connection can be established, the VM continues the build.
        After a period of time passes in which the VM stays idle, it will shut down.

        By default, the VM waits 3 hours before shutting down, but this can be configured using the
        option `onDemand.ttl`.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 31222;
      description = ''
        The SSH port used by the VM.
      '';
    };

    rosetta = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Whether to enable Rosetta support for the VM.

        This is only supported on aarch64-darwin systems and allows the VM to build x86_64-linux
        packages using Rosetta translation. It is recommended to only enable this option if you
        need that functionality, as Rosetta causes a slight performance decrease in VMs when
        enabled, even when it's not being utilized.
      '';
    };

    sharedDirectories = lib.mkOption {
      type = with lib.types; attrsOf str;
      default = { };
      description = ''
        An attribute set of directories that will be shared with the VM as virtio-fs devices.

        The attribute name will be used as the mount tag.
      '';
      example = {
        tmp-share = "/tmp/virby";
      };
    };

    speedFactor = lib.mkOption {
      type = lib.types.int;
      default = 1;
      description = ''
        The speed factor to set for the VM in `nix.buildMachines`.

        This is an arbitrary integer that indicates the speed of this builder, relative to other
        builders. Higher is faster.
      '';
    };
  };
}
