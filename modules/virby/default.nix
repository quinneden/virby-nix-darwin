{ _lib, self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (_lib.constants)
    sshHostPrivateKeyFileName
    sshHostPublicKeyFileName
    sshUserPrivateKeyFileName
    sshUserPublicKeyFileName
    vmHostName
    vmUser
    ;

  inherit (_lib.helpers)
    logError
    logInfo
    parseMemoryString
    setupLogFunctions
    ;

  inherit (lib)
    isString
    makeBinPath
    mkAfter
    mkBefore
    mkDefault
    mkEnableOption
    mkForce
    mkIf
    mkMerge
    mkOption
    optional
    optionalAttrs
    replaceString
    types
    ;

  cfg = config.services.virby;
in
{
  options.services.virby = {
    enable = mkEnableOption "Virby, a vfkit-based linux builder for nix-darwin";

    allowUserSsh = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Whether to allow non-root users to SSH into the VM.

        This is useful for debugging, but it means that any user on the host machine can ssh into
        the VM without root privileges, which could pose a security risk.
      '';
    };

    cores = mkOption {
      type = types.int;
      default = 8;
      description = ''
        The number of CPU cores allocated to the VM.

        This also sets the `nix.buildMachines.max-jobs` setting.
      '';
    };

    debug = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Whether to enable debug logging for the VM.

        When enabled, the launchd daemon will direct all stdout/stderr output to log files, as well
        as the VM's serial output. This is useful for debugging issues with the VM, but it may pose
        a security risk and should only be enabled when necessary.
      '';
    };

    diskSize = mkOption {
      type = types.str;
      default = "100GiB";
      description = ''
        The size of the disk image for the VM.

        The option value must be a string with a number, followed by the suffix "GiB".
      '';
    };

    extraConfig = mkOption {
      type = types.deferredModule;
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

    memory = mkOption {
      type = with types; either int str;
      default = 6144;
      description = ''
        The amount of memory to allocate to the VM in MiB.

        This can be specified as either: an integer representing an amount in MiB, e.g., `6144`, or
        a string, e.g., `"6GiB"`.
      '';
    };

    onDemand = mkOption {
      type =
        with types;
        (submodule {
          options = {
            enable = mkOption {
              type = bool;
              description = ''
                Whether to enable on-demand activation of the VM.
              '';
            };
            ttl = mkOption {
              type = int;
              description = ''
                This specifies the number of minutes of inactivity which must pass before the VM
                shuts down.

                This option is only relevant when `onDemand.enable` is true.
              '';
            };
          };
        });
      default = {
        enable = false;
        ttl = 180;
      };
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

    port = mkOption {
      type = types.port;
      default = 31222;
      description = ''
        The SSH port used by the VM.
      '';
    };

    rosetta = mkOption {
      type =
        with types;
        (submodule {
          options = {
            enable = mkOption {
              type = bool;
              description = ''
                Whether to enable Rosetta.
              '';
            };
          };
        });
      default = {
        enable = false;
      };
      description = ''
        Whether to enable Rosetta support for the VM.

        This is only supported on aarch64-darwin systems and allows the VM to build x86_64-linux
        packages using Rosetta translation. It is recommended to only enable this option if you
        need that functionality, as Rosetta causes a slight performance decrease in VMs when
        enabled, even when it's not being utilized.
      '';
    };

    speedFactor = mkOption {
      type = types.int;
      default = 1;
      description = ''
        The speed factor to set for the VM in `nix.buildMachines`.

        This is an arbitrary integer that indicates the speed of this builder, relative to other
        builders. Higher is faster.
      '';
    };
  };

  config =
    let
      binPath = makeBinPath (
        with pkgs;
        [
          coreutils
          findutils
          gnugrep
          nix
          openssh
          self.packages.${system}.vm-runner
        ]
      );

      linuxSystem = replaceString "darwin" "linux" pkgs.hostPlatform.system;

      imageWithFinalConfig = self.packages.${linuxSystem}.vm-image.override {
        inherit (cfg)
          debug
          extraConfig
          onDemand
          rosetta
          ;
      };

      baseDiskPath = "${workingDirectory}/base.img";
      diffDiskPath = "${workingDirectory}/diff.img";
      imageFileName = replaceString ".raw" ".img" imageWithFinalConfig.passthru.filePath;
      sourceImagePath = "${imageWithFinalConfig}/${imageFileName}";

      memoryMib = if isString cfg.memory then parseMemoryString cfg.memory else cfg.memory;
      sshdKeysSharedDirName = "vm_sshd_keys";
      sshHostKeyAlias = "${vmHostName}-key";

      daemonName = "virbyd";
      workingDirectory = "/var/lib/virby";

      darwinGid = 348;
      darwinGroup = "virby";
      darwinUid = darwinGid;
      darwinUser = "_${darwinGroup}";
      groupPath = "/Groups/${darwinGroup}";
      userPath = "/Users/${darwinUser}";

      vmConfigJson = pkgs.writeText "virby-vm-config.json" (
        builtins.toJSON {
          memory = memoryMib;
          inherit (cfg)
            debug
            cores
            rosetta
            port
            ;
        }
      );

      runnerScript = pkgs.writeShellScript "${daemonName}-runner" ''
        PATH=${binPath}:$PATH

        set -euo pipefail

        should_keygen() {
          local key_files=(
            ${sshdKeysSharedDirName}/${sshHostPrivateKeyFileName}
            ${sshdKeysSharedDirName}/${sshUserPublicKeyFileName}
            ${sshHostPublicKeyFileName}
            ${sshUserPrivateKeyFileName}
          )

          for file in "''${key_files[@]}"; do
            [[ ! -f $file ]] && return 0
          done
        }

        generate_ssh_keys() {
          local temp_dir=$(mktemp -d)
          local temp_host_key="$temp_dir/host_key"
          local temp_user_key="$temp_dir/user_key"
          local user_key_required_mode=${if cfg.allowUserSsh then "644" else "600"}

          trap "rm -rf $temp_dir" RETURN

          ssh-keygen -C ${darwinUser}@darwin -f "$temp_user_key" -N "" -t ed25519 || return 1
          ssh-keygen -C root@${vmHostName} -f "$temp_host_key" -N "" -t ed25519 || return 1

          # Set permissions based on `cfg.allowUserSsh`
          chmod 640 "$temp_host_key.pub" "$temp_user_key.pub"
          chmod 600 "$temp_host_key"
          chmod "$user_key_required_mode" "$temp_user_key"

          # Remove old keys if they exist
          rm -f ${sshUserPrivateKeyFileName} ${sshHostPublicKeyFileName}
          rm -rf ${sshdKeysSharedDirName}

          echo "${sshHostKeyAlias} $(cat $temp_host_key.pub)" > ssh_known_hosts

          mkdir -p ${sshdKeysSharedDirName}

          mv "$temp_user_key" ${sshUserPrivateKeyFileName}
          mv "$temp_host_key.pub" ${sshHostPublicKeyFileName}
          mv "$temp_host_key" ${sshdKeysSharedDirName}/${sshHostPrivateKeyFileName}
          mv "$temp_user_key.pub" ${sshdKeysSharedDirName}/${sshUserPublicKeyFileName}
        }

        trap 'rm -f vfkit-*-*.sock' EXIT INT TERM

        umask 'g-w,o='
        chmod 'g-w,o=x' .

        sourceImageHash=$(nix hash file ${sourceImagePath} 2>/dev/null)
        baseDiskHash=$(nix hash file ${baseDiskPath} 2>/dev/null) || true

        if [[ $sourceImageHash != $baseDiskHash || ! -f ${diffDiskPath} ]]; then
          ${logInfo} "Creating base/diff disk images..."

          rm -f ${baseDiskPath} ${diffDiskPath}

          if ! cp ${sourceImagePath} ${baseDiskPath}; then
            ${logError} "Failed to copy base disk image to ${baseDiskPath}"
            exit 1
          fi
          ${logInfo} "Copied base disk image to ${baseDiskPath}"

          if ! (cp --reflink=always ${baseDiskPath} ${diffDiskPath} && chmod 'u+w' ${diffDiskPath}); then
            ${logError} "Failed to create diff disk image"
            exit 1
          fi
          ${logInfo} "Created diff disk image at ${diffDiskPath} from backing image ${baseDiskPath}"

          if ! truncate -s ${cfg.diskSize} ${diffDiskPath}; then
            ${logError} "Failed to resize diff disk to ${cfg.diskSize}"
            exit 1
          fi
          ${logInfo} "Resized diff disk to ${cfg.diskSize}"
        fi

        if should_keygen; then
          ${logInfo} "Generating SSH keys..."
          if ! generate_ssh_keys; then
            ${logError} "Failed to generate SSH keys"
            exit 1
          fi
        fi

        # If `cfg.allowUserSsh` is true, the user key should be group-readable, otherwise it
        # should be owner-only
        user_key_required_mode=${if cfg.allowUserSsh then "644" else "600"}
        user_key_actual_mode=$(stat -c "%a" ${sshUserPrivateKeyFileName} 2>/dev/null)

        if [[ $user_key_required_mode -ne $user_key_actual_mode ]]; then
          if ! chmod "$user_key_required_mode" ${sshUserPrivateKeyFileName}; then
            ${logError} "Failed to set permissions on ${sshUserPrivateKeyFileName}"
            exit 1
          fi
        fi

        if ! chmod 'go+r' ssh_known_hosts; then
          ${logError} "Failed to set permissions on ssh_known_hosts"
          exit 1
        fi

        ${logInfo} "Starting VM..."

        if ! exec virby-vm; then
          ${logError} "Failed to start the VM"
          exit 1
        fi
      '';
    in
    mkMerge [
      (mkIf (!cfg.enable) {
        system.activationScripts.postActivation.text = mkBefore ''
          ${setupLogFunctions}

          if [[ -d ${workingDirectory} ]]; then
            logInfo "Removing working directory..."
            rm -rf ${workingDirectory}
          fi

          if uid=$(id -u ${darwinUser} 2>/dev/null); then
            if [[ $uid -ne ${toString darwinUid} ]]; then
              logError "Existing user: ${darwinUser} has unexpected UID: $uid"
              exit 1
            fi

            logInfo "Deleting user ${darwinUser}..."
            dscl . -delete ${userPath}
          fi

          unset 'uid'

          if primaryGroupId=$(dscl . -read ${groupPath} 'PrimaryGroupID' 2>/dev/null | cut -d' ' -f2); then
            if [[ $primaryGroupId -ne ${toString darwinGid} ]]; then
              logError "Existing group: ${darwinGroup} has unexpected GID: $primaryGroupId"
              exit 1
            fi

            logInfo "Deleting group ${darwinGroup}..."
            dscl . -delete ${groupPath}
          fi

          unset 'primaryGroupId'
        '';
      })

      (mkIf cfg.enable {
        assertions = [
          {
            assertion = !(pkgs.system != "aarch64-darwin" && cfg.rosetta.enable);
            message = "Rosetta is only supported on aarch64-darwin systems.";
          }
        ];

        system.activationScripts.extraActivation.text = mkAfter ''
          ${setupLogFunctions}

          # Create group
          if ! primaryGroupId=$(dscl . -read ${groupPath} 'PrimaryGroupID' 2>/dev/null | cut -d' ' -f2); then
            logInfo "Creating group ${darwinGroup}..."
            dscl . -create ${groupPath} 'PrimaryGroupID' ${toString darwinGid}
          elif [[ $primaryGroupId -ne ${toString darwinGid} ]]; then
            logError "Existing group: ${darwinGroup} has unexpected GID: $primaryGroupId, expected: ${toString darwinGid}"
            exit 1
          fi

          unset 'primaryGroupId'

          # Create user
          if ! uid=$(id -u ${darwinUser} 2>/dev/null); then
            logInfo "Setting up user ${darwinUser}..."
            dscl . -create ${userPath}
            dscl . -create ${userPath} 'PrimaryGroupID' ${toString darwinGid}
            dscl . -create ${userPath} 'NFSHomeDirectory' ${workingDirectory}
            dscl . -create ${userPath} 'UserShell' /usr/bin/false
            dscl . -create ${userPath} 'IsHidden' 1
            dscl . -create ${userPath} 'UniqueID' ${toString darwinUid}
          elif [[ $uid -ne ${toString darwinUid} ]]; then
            logError "Existing user: ${darwinUser} has unexpected UID: $uid, expected: ${toString darwinUid}"
            exit 1
          fi

          unset 'uid'

          # Setup working directory
          if [[ ! -d ${workingDirectory} ]]; then
            logInfo "Setting up working directory..."
            mkdir -p ${workingDirectory}
            chown ${darwinUser}:${darwinGroup} ${workingDirectory}
          fi
        '';

        environment.etc."ssh/ssh_config.d/100-${vmHostName}.conf".text = ''
          Host ${vmHostName}
            GlobalKnownHostsFile ${workingDirectory}/ssh_known_hosts
            HostKeyAlias ${sshHostKeyAlias}
            Hostname localhost
            IdentityFile ${workingDirectory}/${sshUserPrivateKeyFileName}
            Port ${toString cfg.port}
            StrictHostKeyChecking yes
            User ${vmUser}
        '';

        launchd.daemons = {
          ${daemonName} = {
            path = [ "/bin" ];
            command = runnerScript;

            serviceConfig =
              {
                UserName = darwinUser;
                WorkingDirectory = workingDirectory;
                KeepAlive = !cfg.onDemand.enable;
                ProcessType = "Adaptive";
                Sockets.Listener = optionalAttrs cfg.onDemand.enable {
                  SockFamily = "IPv4";
                  SockNodeName = "localhost";
                  SockServiceName = toString cfg.port;
                };

                EnvironmentVariables = {
                  VIRBY_VM_CONFIG_FILE = toString vmConfigJson;
                } // optionalAttrs cfg.onDemand.enable { VIRBY_SOCKET_ACTIVATION = "1"; };
              }
              // optionalAttrs cfg.debug {
                StandardErrorPath = "/tmp/${daemonName}.stderr.log";
                StandardOutPath = "/tmp/${daemonName}.stdout.log";
              };
          };
        };

        nix = {
          buildMachines = [
            {
              hostName = vmHostName;
              maxJobs = cfg.cores;
              protocol = "ssh-ng";
              supportedFeatures = [
                "benchmark"
                "big-parallel"
                "kvm"
                "nixos-test"
              ];
              speedFactor = cfg.speedFactor;
              systems = [ linuxSystem ] ++ optional cfg.rosetta.enable "x86_64-linux";
            }
          ];

          distributedBuilds = mkForce true;
          settings.builders-use-substitutes = mkDefault true;
        };
      })
    ];
}
