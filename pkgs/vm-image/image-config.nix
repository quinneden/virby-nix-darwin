{
  _lib,
  cfg,
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
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
  imports = [ "${inputs.nixpkgs}/nixos/modules/image/file-options.nix" ];

  boot = {
    enableContainers = lib.mkDefault false;
    kernelParams = [ "console=hvc0" ];
    loader = {
      efi.canTouchEfiVariables = true;
      systemd-boot.enable = true;
      timeout = 0;
    };
  };

  documentation = {
    enable = false;
    nixos.enable = false;
    man.enable = false;
    info.enable = false;
    doc.enable = false;
  };

  environment = {
    defaultPackages = lib.mkDefault [ ];
    stub-ld.enable = lib.mkDefault false;
  };

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

  image = lib.mkForce {
    baseName = "virby-vm-nixos-image-${config.system.nixos.label}-${pkgs.stdenv.hostPlatform.system}";
    extension = "img";
  };

  networking = {
    hostName = lib.mkForce vmHostName;
    dhcpcd.extraConfig = lib.mkForce ''
      clientid ""
    '';
  };

  nix = {
    channel.enable = false;
    registry.nixpkgs.flake = inputs.nixpkgs;

    settings =
      let
        gibibyte = 1024 * 1024 * 1024;
      in
      {
        auto-optimise-store = true;
        experimental-features = [
          "flakes"
          "nix-command"
        ];
        min-free = gibibyte * 5;
        max-free = gibibyte * 7;
        trusted-users = [ vmUser ];
      };
  };

  programs = {
    less.lessopen = lib.mkDefault null;
    command-not-found.enable = lib.mkDefault false;
    fish.generateCompletions = lib.mkDefault false;
  };

  security.sudo = {
    enable = cfg.debug;
    wheelNeedsPassword = !cfg.debug;
  };

  services = {
    getty = lib.optionalAttrs cfg.debug { autologinUser = vmUser; };
    logrotate.enable = lib.mkDefault false;

    openssh = {
      enable = true;
      hostKeys = [ ]; # disable automatic host key generation

      settings = {
        HostKey = sshHostPrivateKeyPath;
        PasswordAuthentication = false;
      };
    };

    udisks2.enable = lib.mkDefault false;
  };

  system = {
    disableInstallerTools = true;
    nixos.revision = null;
    stateVersion = "25.05";
    systemBuilderArgs.allowSubstitutes = true;
  };

  # Virtualization.framework's virtiofs implementation will grant any guest user access
  # to mounted files; they always appear to be owned by the effective UID and so access cannot
  # be restricted.
  # To protect the guest's SSH host key, the VM is configured to prevent any logins (via
  # console, SSH, etc) by default.  This service then runs before sshd, mounts virtiofs,
  # copies the keys to local files (with appropriate ownership and permissions), and unmounts
  # the filesystem before allowing SSH to start.
  # Once SSH has been allowed to start (and given the guest user a chance to log in), the
  # virtiofs must never be mounted again (as the user could have left some process active to
  # read its secrets). This is prevented by `unitconfig.ConditionPathExists` below.
  systemd.services.install-sshd-keys =
    let
      mountTag = "sshd-keys";
      mountPoint = "/var/${mountTag}";
      authorizedKeysDir = "${sshDirPath}/authorized_keys.d";
    in
    {
      description = "Install sshd's host and authorized keys";

      path = with pkgs; [
        coreutils
        mount
        umount
      ];

      before = [ "sshd.service" ];
      requiredBy = [ "sshd.service" ];

      enableStrictShellChecks = true;
      serviceConfig.Type = "oneshot";
      unitConfig.ConditionPathExists = "!${authorizedKeysDir}/${vmUser}";

      script = ''
        mkdir -p ${mountPoint}
        mount -t virtiofs -o nodev,noexec,nosuid,ro ${mountTag} ${mountPoint}

        install -Dm600 -t ${sshDirPath} ${mountPoint}/${sshHostPrivateKeyFileName}
        install -Dm644 ${mountPoint}/${sshUserPublicKeyFileName} ${authorizedKeysDir}/${vmUser}

        umount ${mountPoint}
        rm -rf ${mountPoint}
      '';
    };

  users = {
    allowNoPasswordLogin = true;
    mutableUsers = false;

    users.${vmUser} = {
      isNormalUser = true;
      extraGroups = lib.optional cfg.debug "wheel";
    };
  };

  virtualisation = {
    rosetta.enable = cfg.rosetta;
  };

  xdg = {
    autostart.enable = lib.mkDefault false;
    icons.enable = lib.mkDefault false;
    mime.enable = lib.mkDefault false;
    sounds.enable = lib.mkDefault false;
  };
}
