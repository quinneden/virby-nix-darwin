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
    firewall.enable = false;
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
      # Use standard NixOS host key generation
      hostKeys = [
        {
          path = "/etc/ssh/ssh_host_ed25519_key";
          type = "ed25519";
        }
      ];

      settings = {
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

  # NOTE: The install-sshd-keys service has been replaced by:
  # 1. Standard NixOS hostKeys generation (openssh.hostKeys = [...])
  # 2. User authorized keys via extraConfig (users.users.builder.openssh.authorizedKeys.keys)
  # The old virtiofs mount approach caused service ordering issues with newer NixOS.

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
