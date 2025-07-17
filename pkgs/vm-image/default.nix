{
  _lib,
  inputs,
  lib,
  pkgs,

  debug ? false,
  extraConfig ? { },
  onDemand ? {
    enable = false;
    ttl = 180;
  },
  rosetta ? {
    enable = false;
  },
}:
let
  cfg = { inherit debug onDemand rosetta; };

  nixosSystem = lib.nixosSystem {
    inherit (pkgs) system;
    inherit pkgs;
    specialArgs = { inherit _lib cfg inputs; };
    modules = [
      ./image-config.nix
      extraConfig
    ];
  };
in
nixosSystem.config.system.build.images.raw-efi
