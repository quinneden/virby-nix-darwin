{ _lib, self }:
{
  config,
  lib,
  options,
  pkgs,
  ...
}:

let
  inherit (_lib.constants)
    baseDiskFileName
    diffDiskFileName
    sshdKeysSharedDirName
    sshHostPrivateKeyFileName
    sshHostPublicKeyFileName
    sshKnownHostsFileName
    sshUserPrivateKeyFileName
    sshUserPrivateKeySharedFileName
    sshUserPublicKeyFileName
    vmHostName
    vmUser
    workingDirectory
    ;

  inherit (_lib.helpers)
    doppelganger
    logError
    logInfo
    parseMemoryMiB
    setupLogFunctions
    ;

  cfg = config.services.virby;

  binPath = lib.makeBinPath (
    with pkgs;
    [
      coreutils
      findutils
      gnugrep
      nix
      openssh
      self.packages.${stdenv.hostPlatform.system}.vm-runner
    ]
  );

  linuxSystem = doppelganger pkgs.stdenv.hostPlatform.system;

  imageWithFinalConfig = self.packages.${linuxSystem}.vm-image.override {
    inherit (cfg)
      debug
      extraConfig
      onDemand
      rosetta
      sharedDirectories
      ;
  };

  baseDiskPath = "${workingDirectory}/${baseDiskFileName}";
  diffDiskPath = "${workingDirectory}/${diffDiskFileName}";
  sourceImagePath = "${imageWithFinalConfig}/${imageWithFinalConfig.passthru.filePath}";

  sshHostKeyAlias = "${vmHostName}-key";

  daemonName = "virbyd";

  darwinGid = 348;
  darwinGroup = "virby";
  darwinUid = darwinGid;
  darwinUser = "_${darwinGroup}";
  groupPath = "/Groups/${darwinGroup}";
  userPath = "/Users/${darwinUser}";

  vmConfigJson = pkgs.writeText "virby-vm-config.json" (
    builtins.toJSON {
      cores = cfg.cores;
      debug = cfg.debug;
      memory = parseMemoryMiB cfg.memory;
      on-demand = cfg.onDemand.enable;
      port = cfg.port;
      rosetta = cfg.rosetta;
      ttl = cfg.onDemand.ttl * 60; # Convert to seconds
      shared-dirs = cfg.sharedDirectories;
    }
  );

  prepareVmScript = pkgs.writeShellScript "${daemonName}-prepare-vm" ''
    PATH=${binPath}:$PATH

    set -euo pipefail
    cd ${workingDirectory}

    NEEDS_GENERATE_SSH_KEYS=0

    should_generate_ssh_keys() {
      local key_files=(
        ${sshdKeysSharedDirName}/${sshHostPrivateKeyFileName}
        ${sshdKeysSharedDirName}/${sshUserPublicKeyFileName}
        ${sshHostPublicKeyFileName}
        ${sshUserPrivateKeyFileName}
      )

      [[ $NEEDS_GENERATE_SSH_KEYS == 1 ]] && return 0

      for file in "''${key_files[@]}"; do
        [[ ! -f $file ]] && return 0
      done
    }

    generate_ssh_keys() {
      local temp_dir=$(mktemp -d)
      local temp_host_key="$temp_dir/host_key"
      local temp_user_key="$temp_dir/user_key"

      trap "rm -rf $temp_dir" RETURN

      ssh-keygen -C ${darwinUser}@darwin -f "$temp_user_key" -N "" -t ed25519 || return 1
      ssh-keygen -C root@${vmHostName} -f "$temp_host_key" -N "" -t ed25519 || return 1

      chmod 640 "$temp_host_key.pub" "$temp_user_key.pub"
      chmod 600 "$temp_host_key"
      chmod 600 "$temp_user_key"

      # Remove old keys if they exist
      rm -f ${sshUserPrivateKeyFileName} ${sshUserPrivateKeySharedFileName} ${sshHostPublicKeyFileName}
      rm -rf ${sshdKeysSharedDirName}

      echo "${sshHostKeyAlias} $(cat $temp_host_key.pub)" > ${sshKnownHostsFileName}

      mkdir -p ${sshdKeysSharedDirName}

      mv "$temp_user_key" ${sshUserPrivateKeyFileName}
      mv "$temp_host_key.pub" ${sshHostPublicKeyFileName}
      mv "$temp_host_key" ${sshdKeysSharedDirName}/${sshHostPrivateKeyFileName}
      mv "$temp_user_key.pub" ${sshdKeysSharedDirName}/${sshUserPublicKeyFileName}
    }

    umask 'g-w,o='
    chmod 'g-w,o=x' .

    source_image_path_marker="${workingDirectory}/.disk-image-store-path"
    current_source_image_path=$(cat $source_image_path_marker 2>/dev/null) || true

    if [[ ! -f ${diffDiskPath} ]] || [[ $current_source_image_path != ${imageWithFinalConfig} ]]; then
      ${logInfo} "Creating VM disk images..."

      rm -f ${baseDiskPath} ${diffDiskPath}

      if ! cp ${sourceImagePath} ${baseDiskPath}; then
        ${logError} "Failed to copy source image to ${baseDiskPath}"
        exit 1
      fi
      ${logInfo} "Copied base disk image to ${baseDiskPath}"

      if ! (cp --reflink=always ${baseDiskPath} ${diffDiskPath} && chmod 'u+w' ${diffDiskPath}); then
        ${logError} "Failed to create diff disk image"
        exit 1
      fi
      ${logInfo} "Created diff disk image: ${diffDiskPath}"

      if ! truncate -s ${cfg.diskSize} ${diffDiskPath}; then
        ${logError} "Failed to resize diff disk image to ${cfg.diskSize}"
        exit 1
      fi
      ${logInfo} "Resized diff disk image to ${cfg.diskSize}"

      echo ${imageWithFinalConfig} > "$source_image_path_marker"

      NEEDS_GENERATE_SSH_KEYS=1
    fi

    if should_generate_ssh_keys; then
      ${logInfo} "Generating SSH keys..."
      if ! generate_ssh_keys; then
        ${logError} "Failed to generate SSH keys"
        exit 1
      fi
    fi

    # The runner always uses the private key directly, so it must stay owner-only.
    user_key_required_mode=600
    user_key_actual_mode=$(stat -c "%a" ${sshUserPrivateKeyFileName} 2>/dev/null)

    if [[ $user_key_required_mode -ne $user_key_actual_mode ]]; then
      if ! chmod "$user_key_required_mode" ${sshUserPrivateKeyFileName}; then
        ${logError} "Failed to set permissions on ${sshUserPrivateKeyFileName}"
        exit 1
      fi
    fi

    if [[ ${if cfg.allowUserSsh then "1" else "0"} -eq 1 ]]; then
      if ! cp -f ${sshUserPrivateKeyFileName} ${sshUserPrivateKeySharedFileName}; then
        ${logError} "Failed to create shared SSH key copy"
        exit 1
      fi

      if ! chmod 644 ${sshUserPrivateKeySharedFileName}; then
        ${logError} "Failed to set permissions on ${sshUserPrivateKeySharedFileName}"
        exit 1
      fi
    else
      rm -f ${sshUserPrivateKeySharedFileName}
    fi

    if ! [[ -f ${sshHostPublicKeyFileName} ]]; then
      ${logError} "Missing host public key: ${sshHostPublicKeyFileName}"
      exit 1
    fi

    echo "${sshHostKeyAlias} $(cat ${sshHostPublicKeyFileName})" > ${sshKnownHostsFileName}

    if ! chmod 'go+r' ${sshKnownHostsFileName}; then
      ${logError} "Failed to set permissions on ${sshKnownHostsFileName}"
      exit 1
    fi
  '';

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
      systems = [ linuxSystem ] ++ lib.optional cfg.rosetta "x86_64-linux";
    }
  ];

  distributedBuilds = lib.mkForce true;
in

{
  imports = [ ./options.nix ];

  config = lib.mkMerge [
    (lib.mkIf (!cfg.enable) {
      system.activationScripts.postActivation.text = lib.mkBefore ''
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

    (lib.mkIf cfg.enable {
      assertions = [
        {
          assertion = !(pkgs.stdenv.hostPlatform.system != "aarch64-darwin" && cfg.rosetta);
          message = "Rosetta is only supported on aarch64-darwin systems.";
        }
      ];

      system.activationScripts.extraActivation.text = lib.mkAfter ''
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
        fi

        chown ${darwinUser}:${darwinGroup} ${workingDirectory}

        logInfo "Preparing Virby VM runtime files..."
        if ! ${prepareVmScript}; then
          logError "Failed to prepare Virby VM runtime files"
          exit 1
        fi

        chown -R ${darwinUser}:${darwinGroup} ${workingDirectory}
      '';

      environment.etc."ssh/ssh_config.d/100-${vmHostName}.conf".text = ''
        Host ${vmHostName}
          GlobalKnownHostsFile ${workingDirectory}/${sshKnownHostsFileName}
          UserKnownHostsFile /dev/null
          HostKeyAlias ${sshHostKeyAlias}
          Hostname localhost
          AddressFamily inet
          IdentitiesOnly yes
          IdentityFile ${workingDirectory}/${
            if cfg.allowUserSsh then sshUserPrivateKeySharedFileName else sshUserPrivateKeyFileName
          }
          Port ${toString cfg.port}
          StrictHostKeyChecking yes
          User ${vmUser}
      '';

      launchd.daemons = {
        ${daemonName} = {
          path =
            with pkgs;
            [
              coreutils
              findutils
              gnugrep
              nix
              openssh
              self.packages.${pkgs.stdenv.hostPlatform.system}.vm-runner
            ];
          command = lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.vm-runner;

          serviceConfig = {
            UserName = darwinUser;
            WorkingDirectory = workingDirectory;
            KeepAlive = !cfg.onDemand.enable;

            Sockets.Listener = {
              SockFamily = "IPv4";
              SockNodeName = "localhost";
              SockServiceName = toString cfg.port;
            };

            EnvironmentVariables = {
              VIRBY_VM_CONFIG_FILE = toString vmConfigJson;
            };
          }
          // lib.optionalAttrs cfg.debug { StandardOutPath = "/tmp/${daemonName}.log"; };
        };
      };

      system.build.virbyImage = imageWithFinalConfig;
    })

    (lib.mkIf (!cfg.supportDeterminateNix) {
      nix = {
        inherit buildMachines distributedBuilds;
        settings.builders-use-substitutes = lib.mkDefault true;
      };
    })

    (lib.mkIf cfg.supportDeterminateNix (
      {
        assertions = [
          {
            assertion = config.determinateNix.enable or false;
            message = ''
              `supportDeterminateNix = true` requires the Determinate module for Nix-darwin to be enabled.

              To enable:
              - Add `determinate.url = "github:determinatesystems/determinate"` to your flake inputs.
              - Include `inputs.determinate.darwinModules.default` in your imports.
              - Set `determinateNix.enable = true`.
            '';
          }
        ];
      }
      // lib.optionalAttrs (options ? determinateNix) {
        determinateNix = {
          inherit buildMachines distributedBuilds;
          customSettings.builders-use-substitutes = lib.mkDefault true;
        };
      }
    ))
  ];
}
