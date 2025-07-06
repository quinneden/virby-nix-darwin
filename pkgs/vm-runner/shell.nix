{
  pkgs ? import <nixpkgs> { },
}:
pkgs.mkShellNoCC {
  name = "virby-vm-runner";
  packages = with pkgs; [
    gvproxy
    vfkit
  ];
}
