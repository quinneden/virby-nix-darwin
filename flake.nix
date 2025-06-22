{
  description = "A vfkit-based linux builder for Nix-darwin";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixpkgs-unstable";
  };

  outputs =
    { self, nixpkgs }@inputs:
    let
      inherit (nixpkgs) lib;
      _lib = import ./lib { inherit lib; };

      darwinSystems = lib.systems.doubles.darwin;
      linuxSystems = lib.forEach darwinSystems (f: lib.replaceString "darwin" "linux" f);

      perSystem = systems: f: lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));

      perDarwinSystem = perSystem darwinSystems;
      perLinuxSystem = perSystem linuxSystems;
    in
    {
      darwinModules = {
        default = self.darwinModules.virby;
        virby = import ./modules/virby { inherit _lib self; };
      };

      packages = perLinuxSystem (pkgs: {
        default = self.packages.${pkgs.system}.vm-image;
        vm-image = pkgs.callPackage ./pkgs/vm-image { inherit _lib inputs lib; };
      });

      devShells = perDarwinSystem (pkgs: {
        default = pkgs.mkShell { buildInputs = [ pkgs.vfkit ]; };
      });

      formatter = perDarwinSystem (pkgs: pkgs.nixfmt-rfc-style);
    };
}
