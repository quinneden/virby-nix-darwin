{
  buildGoModule,
  lib,
  vfkit,
}:

buildGoModule {
  name = "virby-vm-runner";
  src = ./.;

  vendorHash = null;

  ldflags = [ "-X vm-runner/internal/vmprocess.vfkitBin=${lib.getExe vfkit}" ];

  meta = {
    description = "Vfkit-based VM runner for Virby";
    homepage = "https://github.com/quinneden/virby-nix-darwin";
    license = lib.licenses.mit;
    platforms = lib.platforms.darwin;
    mainProgram = "virby-vm";
  };
}
