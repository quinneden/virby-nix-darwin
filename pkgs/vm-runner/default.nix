{ buildGoModule, lib }:

buildGoModule {
  name = "virby-vm-runner";
  src = ./.;

  vendorHash = "sha256-Ivlyju4bHiKAfCKAYUmmoQzChD6o1kHE7dSrFwz7aDU=";

  meta = {
    description = "VM runner for Virby";
    homepage = "https://github.com/quinneden/virby-nix-darwin";
    license = lib.licenses.mit;
    platforms = lib.platforms.darwin;
    mainProgram = "virby-vm";
  };
}
