{
  _lib,
  cfg,
  inputs,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib)
    mkDefault
    mkForce
    optional
    optionalAttrs
    trivial
    versions
    ;

  inherit (_lib.constants)
    sshHostPrivateKeyFileName
    sshUserPublicKeyFileName
    vmHostName
    vmUser
    ;

  sshDirPath = "/etc/ssh/";
  sshHostPrivateKeyPath = sshDirPath + sshHostPrivateKeyFileName;
in
{
  boot = mkForce {
    kernelParams = [ "console=hvc0" ];
    loader = {
      efi.canTouchEfiVariables = true;
      systemd-boot.enable = true;
      timeout = 0;
    };
  };

  documentation.enable = mkDefault false;

  fileSystems = {
    "/".options = [
      "discard"
      "noatime"
    ];
    "/boot".options = [
      "discard"
      "noatime"
      "umask=0077"
    ];
  };

  networking.hostName = mkForce vmHostName;

  nix = mkDefault {
    channel.enable = false;
    registry.nixpkgs.flake = inputs.nixpkgs;

    settings = {
      auto-optimise-store = true;
      experimental-features = [
        "flakes"
        "nix-command"
      ];
      min-free = "5G";
      max-free = "7G";
      trusted-users = [ vmUser ];
    };
  };

  security = mkForce {
    sudo = {
      enable = cfg.debug;
      wheelNeedsPassword = !cfg.debug;
    };
  };

  services = {
    getty = optionalAttrs cfg.debug { autologinUser = vmUser; };

    logind = optionalAttrs cfg.onDemand.enable {
      extraConfig = mkForce ''
        IdleAction=poweroff
        IdleActionSec=${toString cfg.onDemand.ttl}minutes
      '';
    };
    openssh = mkForce {
      enable = true;
      hostKeys = [ ]; # disable automatic host key generation

      settings = {
        HostKey = sshHostPrivateKeyPath;
        PasswordAuthentication = false;
      };
    };
  };

  system = mkDefault {
    disableInstallerTools = true;
    stateVersion = versions.majorMinor trivial.version;
  };

  # macOS' Virtualization framework's virtiofs implementation will grant any guest user access
  # to mounted files; they always appear to be owned by the effective UID and so access cannot
  # be restricted.
  # To protect the guest's SSH host key, the VM is configured to prevent any logins (via
  # console, SSH, etc) by default.  This service then runs before sshd, mounts virtiofs,
  # copies the keys to local files (with appropriate ownership and permissions), and unmounts
  # the filesystem before allowing SSH to start.
  # Once SSH has been allowed to start (and given the guest user a chance to log in), the
  # virtiofs must never be mounted again (as the user could have left some process active to
  # read its secrets).  This is prevented by `unitconfig.ConditionPathExists` below.
  systemd.services.install-sshd-keys =
    let
      mountTag = "sshd-keys";
      mountPoint = "/var/${mountTag}";
      authorizedKeysDir = "${sshDirPath}/authorized_keys.d";
    in
    {
      description = "Install sshd's host and authorized keys";

      path = with pkgs; [
        mount
        umount
      ];

      before = [ "sshd.service" ];
      requiredBy = [ "sshd.service" ];

      enableStrictShellChecks = true;
      serviceConfig.Type = "oneshot";
      unitConfig.ConditionPathExists = "!${authorizedKeysDir}/${vmUser}";

      # must be idempotent in the face of partial failues
      script = ''
        mkdir -p ${mountPoint} ${sshDirPath} ${authorizedKeysDir}
        mount -t virtiofs -o nodev,noexec,nosuid,ro ${mountTag} ${mountPoint}

        (
          umask 'go='
          cp ${mountPoint}/${sshHostPrivateKeyFileName} ${sshHostPrivateKeyPath}
        )

        cp ${mountPoint}/${sshUserPublicKeyFileName} ${authorizedKeysDir}/${vmUser}.tmp
        chmod 'a+r' ${authorizedKeysDir}/${vmUser}.tmp

        umount ${mountPoint}
        rm -rf ${mountPoint}

        # must be last so only now `unitConfig.ConditionPathExists` triggers
        mv ${authorizedKeysDir}/${vmUser}.tmp ${authorizedKeysDir}/${vmUser}
      '';
    };

  users = mkForce {
    # console and (initial) SSH logins are purposefully disabled
    # see: `systemd.services.install-sshd-keys`
    allowNoPasswordLogin = true;
    mutableUsers = false;

    users.${vmUser} = {
      isNormalUser = true;
      extraGroups = optional cfg.debug "wheel";
    };
  };

  virtualisation = { inherit (cfg) rosetta; };
}
