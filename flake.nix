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

      darwinSystem = "aarch64-darwin";
      linuxSystem = "aarch64-linux";
      systems = [
        darwinSystem
        linuxSystem
      ];

      forSystem = lib.genAttrs systems (
        system: (f: { ${system} = f (import nixpkgs { inherit system; }); })
      );
    in

    {
      darwinModules = {
        default = self.darwinModules.virby;
        virby = import ./module { inherit _lib self; };
      };

      packages =
        forSystem.aarch64-darwin (pkgs: {
          default = self.packages.${pkgs.stdenv.hostPlatform.system}.vm-runner;
          vm-runner = pkgs.callPackage ./pkgs/vm-runner { };
        })
        // forSystem.aarch64-linux (pkgs: {
          default = self.packages.${pkgs.stdenv.hostPlatform.system}.vm-image;
          vm-image = pkgs.callPackage ./pkgs/vm-image { inherit _lib inputs lib; };
        });

      devShells = forSystem.aarch64-darwin (pkgs: {
        default = pkgs.mkShellNoCC {
          name = "virby-dev";
          packages = [ pkgs.vfkit ];
        };
      });

      formatter = forSystem.aarch64-darwin (
        pkgs: pkgs.nixfmt-tree.override { settings.formatter.nixfmt.options = [ "--strict" ]; }
      );
    };
}
