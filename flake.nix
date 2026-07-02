{
  description = "A {krun|vf}kit-based linux builder for Nix-darwin";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixpkgs-unstable";
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
        system:
        (f: {
          ${system} = f (
            import nixpkgs {
              inherit system;
              overlays = [ self.overlays.default ];
            }
          );
        })
      );
    in

    {
      darwinModules = {
        default = self.darwinModules.virby;
        virby = import ./module { inherit _lib self; };
      };

      devShells = forSystem.aarch64-darwin (pkgs: {
        default = pkgs.mkShellNoCC {
          name = "virby-dev";
          packages = with pkgs; [
            krunkit
            vfkit
          ];
        };
      });

      formatter = forSystem.aarch64-darwin (
        pkgs: pkgs.nixfmt-tree.override { settings.formatter.nixfmt.options = [ "--strict" ]; }
      );

      overlays.default = final: prev: {
        # FIXME: remove when https://github.com/NixOS/nixpkgs/pull/525378 is merged
        krunkit = prev.krunkit.overrideAttrs (old: {
          postInstall = (prev.postInstall or "") + ''
            install -Dm444 edk2/KRUN_EFI.silent.fd $out/share/krunkit/KRUN_EFI.silent.fd
          '';
        });

        # FIXME: remove when https://github.com/NixOS/nixpkgs/pull/495633 is merged
        vmnet-helper = final.callPackage ./pkgs/vmnet-helper { };
      };

      packages =
        forSystem.aarch64-darwin (pkgs: {
          default = self.packages.${darwinSystem}.vm-runner;
          vm-runner = pkgs.callPackage ./pkgs/vm-runner { };
        })
        // forSystem.aarch64-linux (pkgs: {
          default = self.packages.${linuxSystem}.vm-image;
          vm-image = pkgs.callPackage ./pkgs/vm-image { inherit _lib inputs lib; };
        });
    };
}
