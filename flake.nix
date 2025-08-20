{
  description = "A vfkit-based linux builder for Nix-darwin";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
  };

  outputs =
    { self, nixpkgs }@inputs:

    let
      inherit (nixpkgs) lib;
      _lib = import ./lib { inherit lib; };

      darwinSystems = lib.systems.doubles.darwin;
      linuxSystems = _lib.helpers.doppelganger darwinSystems;

      pkgsFor = systems: f: lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));

      perDarwinSystem = pkgsFor darwinSystems;
      perLinuxSystem = pkgsFor linuxSystems;
    in

    {
      darwinModules = {
        default = self.darwinModules.virby;
        virby = import ./module { inherit _lib self; };
      };

      packages =
        perDarwinSystem (pkgs: {
          default = self.packages.${pkgs.system}.vm-runner;
          vm-runner = pkgs.python3Packages.callPackage ./pkgs/vm-runner { inherit _lib; };
        })
        // perLinuxSystem (pkgs: {
          default = self.packages.${pkgs.system}.vm-image;
          vm-image = pkgs.callPackage ./pkgs/vm-image { inherit _lib inputs lib; };
        });

      apps = perDarwinSystem (pkgs: {
        benchmark-vm = {
          type = "app";
          program = lib.getExe (pkgs.callPackage ./scripts/benchmark-vm { });
        };
        bump-version = {
          type = "app";
          program = lib.getExe (pkgs.callPackage ./scripts/bump-version { });
        };
      });

      devShells = perDarwinSystem (pkgs: {
        default = pkgs.mkShellNoCC {
          name = "virby-dev";
          packages = [ pkgs.vfkit ];
        };
      });

      formatter = perDarwinSystem (pkgs: pkgs.nixfmt-tree);
    };
}
