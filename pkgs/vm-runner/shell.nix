{
  pkgs ? import <nixpkgs> { },
}:
pkgs.mkShellNoCC {
  name = "vm-runner";
  packages = with pkgs; [
    gvproxy
    vfkit
  ];
}
