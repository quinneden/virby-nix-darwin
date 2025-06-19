{
  _lib,
  inputs,
  lib,
  pkgs,

  debug ? _lib.defaults.debug,
  extraConfig ? _lib.defaults.extraConfig,
  onDemand ? _lib.defaults.onDemand,
  rosetta ? _lib.defaults.rosetta,
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
