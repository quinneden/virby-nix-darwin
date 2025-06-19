{ _lib, self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let

  inherit (_lib.constants)
    name
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
    concatStringsSep
    getExe
    isString
    mkAfter
    mkBefore
    mkEnableOption
    mkDefault
    mkIf
    mkForce
    mkMerge
    mkOption
    optional
    optionals
    optionalAttrs
    optionalString
    replaceString
    types
    ;

  cfg = config.services.virby;
in
{
  options.services.virby = {
    enable = mkEnableOption "${name}, a vfkit-based linux builder for nix-darwin";

    allowUserSsh = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Whether to allow non-root users to SSH into the VM.

        This is useful for debugging, but it means that any user on the host
        machine can ssh into the VM without requiring root privileges, which
        could pose a security risk.
      '';
    };

    cores = mkOption {
      type = types.int;
      default = 8;
      description = ''
        The number of CPU cores allocated to the VM.

        This also sets the maximum number of jobs allowed for the builder in
        the `nix.buildMachines` specification.
      '';
    };

    debug = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Whether to enable debug logging for the VM.

        When enabled, the VM and daemon will log additional information to help
        with debugging issues.
      '';
    };

    diskSize = mkOption {
      type = types.str;
      default = "100GiB";
      description = ''
        The size of the disk image for the VM.

        This must be specified as a string in the format: "xGiB", where "x" is
        a number of GiB.
      '';
    };

    extraConfig = mkOption {
      type = types.deferredModule;
      default = { };
      description = ''
        Extra NixOS configuration module to pass to the VM.

        The VM's default configuration allows it to be securely used as a
        builder. Some extra configuration changes may endager this security and
        allow compromised deriviations into the host's Nix store. Care should
        be taken to think through the implications of any extra configuration
        changes using this option. When in doubt, please open a GitHub issue to
        discuss (additional, restricted options can be added to support safe
        configurations).
      '';
    };

    memory = mkOption {
      type = with types; either int str;
      default = 6144;
      description = ''
        The amount of memory to allocate to the VM in MiB.

        This can be specified as an integer representing an amount in MiB,
        e.g., 6144, or a string, e.g. "6GiB".
      '';
    };

    onDemand = mkOption {
      type =
        with types;
        submodule {
          options = {
            enable = mkEnableOption "on-demand mode for the VM";
            ttl = mkOption {
              type = int;
              default = 180;
              description = ''
                This specifies the number of minutes of inactivity which must
                pass before the VM shuts down.

                This option is only relevant when `onDemand.enable` is true.
              '';
            };
          };
        };
      description = ''
        By default, the VM is always-on, running as a daemon in the background.
        This allows builds to started right away, but also means the VM will
        always be consuming (a small amount of) cpu and memory resources.

        When enabled, this option will allow the VM to be activated on-demand;
        when not in use, the VM will not be running. When a build job requiring
        use of the VM is initiated, it signals the VM to start, and once an SSH
        connection can be established, the VM continues the build. After a
        period of idle time passes, the VM will shut down.

        By default, the VM waits 3 hours before shutting down, but this can be
        configured with a different value by specifying `onDemand.ttl`.
      '';
    };

    port = mkOption {
      type = types.port;
      default = 31177;
      description = ''
        The SSH port used by the VM.
      '';
    };

    rosetta = mkOption {
      type = types.submodule {
        options = {
          enable = mkEnableOption "Rosetta support for the VM";
        };
      };
      description = ''
        Whether to enable Rosetta support for the VM.

        This is only supported on aarch64-darwin systems and allows the VM to
        build x86_64-linux packages using Rosetta translation.
      '';
    };
  };

  config =
    let
      baseDiskPath = "${workingDirectory}/base.img";
      diffDiskPath = "${workingDirectory}/diff.img";
      imageFileName = replaceString ".raw" ".img" imageWithFinalConfig.passthru.filePath;
      imageWithFinalConfig = vm-image.override { inherit (cfg) extraConfig onDemand rosetta; };
      linuxSystem = replaceString "darwin" "linux" pkgs.system;
      sourceImage = "${imageWithFinalConfig}/${imageFileName}";
      vm-image = self.packages.${linuxSystem}.vm-image;

      efiVariableStorePath = "${workingDirectory}/${vmHostName}.efistore";
      memoryMib = if isString cfg.memory then parseMemoryString cfg.memory else cfg.memory;
      networkSocketPath = "${workingDirectory}/${vmHostName}-network.sock";
      serialLogFile = "/tmp/${vmHostName}.serial.log";
      sshdKeysSharedDirName = "vm-sshd-keys";
      sshHostKeyAlias = "${vmHostName}-key";

      daemonName = "${name}d";
      gvproxyDaemonName = "${name}-gvproxyd";
      workingDirectory = "/var/lib/${daemonName}";

      darwinGid = 348;
      darwinGroup = "${name}";
      darwinUid = darwinGid;
      darwinUser = "_${darwinGroup}";
      groupPath = "/Groups/${darwinGroup}";
      userPath = "/Users/${darwinUser}";

      vfkitCommand = concatStringsSep " " (
        [
          (getExe pkgs.vfkit)
          "--cpus"
          (toString cfg.cores)
          "--memory"
          (toString memoryMib)
          "--bootloader"
          "efi,variable-store=${efiVariableStorePath},create"
          "--device"
          "virtio-blk,path=${diffDiskPath}"
          "--device"
          "virtio-fs,sharedDir=${workingDirectory}/${sshdKeysSharedDirName},mountTag=sshd-keys"
          "--device"
          "virtio-net,unixSocketPath=${networkSocketPath},mac=5a:94:ef:e4:0c:ee"
          "--device"
          "virtio-balloon"
          "--device"
          "virtio-rng"
        ]
        ++ optionals cfg.debug [
          "--device"
          "virtio-serial,logFilePath=${serialLogFile}"
        ]
        ++ optionals cfg.rosetta.enable [
          "--device"
          "rosetta,mountTag=rosetta"
        ]
      );

      runnerScript = pkgs.writeShellScript "${daemonName}-runner" ''
        set -xeuo pipefail

        check_gvproxyd_status() {
          if launchctl list | grep -q "org.nixos.${gvproxyDaemonName}"; then
            local pid=$(launchctl list | grep "org.nixos.${gvproxyDaemonName}" | cut -f1)
            if [[ -n $pid && $pid != "-" ]]; then
              return 0  # Service is running
            else
              return 1  # Service is loaded but not running
            fi
          else
            return 2  # Service is not loaded
          fi
        }

        kickstart_gvproxyd() {
          if launchctl kickstart "org.nixos.${gvproxyDaemonName}"; then
            ${logInfo} "Successfully kickstarted org.nixos.${gvproxyDaemonName}"
            return 0
          else
            ${logError} "Failed to kickstart org.nixos.${gvproxyDaemonName}"
            return 1
          fi
        }

        bootstrap_gvproxyd() {
          local plist_path="/Library/LaunchDaemons/org.nixos.${gvproxyDaemonName}.plist"

          if [[ ! -f $plist_path ]]; then
            ${logError} "$plist_path does not exist"
            return 1
          fi

          if launchctl bootstrap system "$plist_path"; then
            ${logInfo} "Successfully bootstrapped org.nixos.${gvproxyDaemonName}"
            return 0
          else
            ${logError} "Failed to bootstrap org.nixos.${gvproxyDaemonName}"
            return 1
          fi
        }

        cleanup() {
          ${logInfo} "Cleaning up resources..."
          rm -f ${efiVariableStorePath} ${workingDirectory}/vfkit-*-*.sock
        }

        trap cleanup EXIT INT TERM

        umask 'g-w,o='
        chmod 'g-w,o=x' .

        # Setup SSH keys (idempotent)
        if ! find ${sshUserPrivateKeyFileName} -perm '${
          if cfg.allowUserSsh then "-go=r" else "+go=r"
        }' -exec true '{}' '+' 2>/dev/null; then
          rm -f ${sshUserPrivateKeyFileName} ${sshUserPublicKeyFileName}
          ssh-keygen -C ${darwinUser}@darwin -f ${sshUserPrivateKeyFileName} -N "" -t ed25519

          rm -f ${sshHostPrivateKeyFileName} ${sshHostPublicKeyFileName}
          ssh-keygen -C root@${vmHostName} -f ${sshHostPrivateKeyFileName} -N "" -t ed25519

          mkdir -p ${sshdKeysSharedDirName}
          mv ${sshUserPublicKeyFileName} ${sshHostPrivateKeyFileName} ${sshdKeysSharedDirName}

          echo ${sshHostKeyAlias} "$(cat ${sshHostPublicKeyFileName})" > ssh_known_hosts
        fi

        sourceImageHash=$(nix hash file ${sourceImage} 2>/dev/null)
        baseDiskHash=$(nix hash file ${baseDiskPath} 2>/dev/null || true)

        if [[ $sourceImageHash != $baseDiskHash || ! -f ${diffDiskPath} ]]; then
          ${logInfo} "Creating base/diff disk images..."

          rm -f ${baseDiskPath} ${diffDiskPath}

          if ! cp ${sourceImage} ${baseDiskPath} && chmod 'g+r' ${baseDiskPath}; then
            ${logError} "Failed to copy base disk image to ${baseDiskPath}"
            exit 1
          fi
          ${logInfo} "Copied base disk image to ${baseDiskPath}"

          if ! cp --reflink=always ${baseDiskPath} ${diffDiskPath} && chmod 'u+w'; then
            ${logError} "Failed to create copy-on-write image at ${diffDiskPath} from backing image ${baseDiskPath}"
            exit 1
          fi
          ${logInfo} "Created copy-on-write image at ${diffDiskPath} from backing image ${baseDiskPath}"

          if ! truncate -s ${cfg.diskSize} ${diffDiskPath}; then
            ${logError} "Failed to resize diff disk to ${cfg.diskSize}"
            exit 1
          fi
          ${logInfo} "Resized diff disk to ${cfg.diskSize}"
        fi

        # Set SSH file permissions
        chmod 'go+r' ssh_known_hosts
        ${optionalString cfg.allowUserSsh "chmod 'go+r' ${sshUserPrivateKeyFileName}"}

        SLEEP_INTERVAL=5
        MAX_RETRIES=6

        ${logInfo} "Starting monitoring loop for ${gvproxyDaemonName}"

        while true; do
          check_gvproxyd_status
          status=$?
          case $status in
            0)
              ${logInfo} "${gvproxyDaemonName} is running, breaking loop..."
              break
              ;;
            1)
              ${logInfo} "${gvproxyDaemonName} is loaded but not running, kickstarting..."
              retry_count=0

              while [[ $retry_count -lt $MAX_RETRIES ]]; do
                kickstart_gvproxyd && break
                retry_count=$((retry_count + 1))
                sleep $SLEEP_INTERVAL
              done

              ${logInfo} "Failed to start ${gvproxyDaemonName} after $MAX_RETRIES attempts"
              exit 1
              ;;
            2)
              ${logInfo} "org.nixos.${gvproxyDaemonName} is not loaded, bootstrapping..."
              bootstrap_gvproxyd
              ;;
          esac

          sleep $SLEEP_INTERVAL
        done

        ${logInfo} "Starting VM with command: ${vfkitCommand}"

        if ! exec ${vfkitCommand}; then
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
            logInfo "removing working directory ${workingDirectory}..."
            rm -rf ${workingDirectory}
          fi

          if uid=$(id -u ${darwinUser} 2>'/dev/null'); then
            if [[ $uid -ne ${toString darwinUid} ]]; then
              logError "existing user: ${darwinUser} has unexpected UID: $uid"
              exit 1
            fi
            logInfo "deleting user ${darwinUser}..."
            dscl . -delete ${userPath}
          fi

          unset 'uid'

          if primaryGroupId=$(dscl . -read ${groupPath} 'PrimaryGroupID' 2>'/dev/null'); then
            if [[ "$primaryGroupId" != *\ ${toString darwinGid} ]]; then
              logError "Existing group: ${darwinGroup} has unexpected GID: $primaryGroupId"
              exit 1
            fi
            log "deleting group ${darwinGroup}..."
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
          if ! primaryGroupId=$(dscl . -read ${groupPath} 'PrimaryGroupID' 2>'/dev/null'); then
            logInfo "Creating group ${darwinGroup} with GID ${toString darwinGid}..."
            dscl . -create ${groupPath} 'PrimaryGroupID' ${toString darwinGid}
          elif [[ "$primaryGroupId" != *\ ${toString darwinGid} ]]; then
            logError "Existing group: ${darwinGroup} has unexpected GID: $primaryGroupId"
            exit 1
          fi

          # Create user
          if ! uid=$(id -u ${darwinUser} 2>'/dev/null'); then
            logInfo "Setting up user ${darwinUser} with UID ${toString darwinUid}..."
            dscl . -create ${userPath}
            dscl . -create ${userPath} 'PrimaryGroupID' ${toString darwinGid}
            dscl . -create ${userPath} 'NFSHomeDirectory' ${workingDirectory}
            dscl . -create ${userPath} 'UserShell' '/usr/bin/false'
            dscl . -create ${userPath} 'IsHidden' 1
            dscl . -create ${userPath} 'UniqueID' ${toString darwinUid}
          elif [[ $uid -ne ${toString darwinUid} ]]; then
            logError "Existing user: ${darwinUser} has unexpected UID: $uid"
            exit 1
          fi

          # Setup working directory
          logInfo "Setting up ${name} working directory ${workingDirectory}..."
          mkdir -p ${workingDirectory}
          chown ${darwinUser}:${darwinGroup} ${workingDirectory}
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
          ${gvproxyDaemonName} = {
            script = concatStringsSep " " [
              "exec"
              (pkgs.gvproxy + "/bin/gvproxy")
              "-listen-vfkit"
              ("unixgram://" + networkSocketPath)
              "-ssh-port"
              (toString cfg.port)
            ];

            serviceConfig =
              {
                UserName = darwinUser;
                WorkingDirectory = workingDirectory;
                RunAtLoad = true;
                KeepAlive = true;
                ProcessType = "Background";
              }
              // optionalAttrs cfg.debug {
                StandardErrorPath = "/tmp/${gvproxyDaemonName}.stderr.log";
                StandardOutPath = "/tmp/${gvproxyDaemonName}.stdout.log";
              };
          };

          ${daemonName} = {
            path = with pkgs; [
              coreutils
              findutils
              gnugrep
              nix
              openssh
              vfkit
              "/usr/bin"
              "/bin"
              "/usr/sbin"
              "/sbin"
            ];

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
              systems = [ linuxSystem ] ++ optional cfg.rosetta.enable "x86_64-linux";
            }
          ];

          distributedBuilds = mkForce true;
          settings.builders-use-substitutes = mkDefault true;
        };
      })
    ];
}
