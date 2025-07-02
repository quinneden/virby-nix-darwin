{
  lib,
  aiofiles,
  buildPythonPackage,
  hatchling,
  vfkit,
}:

buildPythonPackage {
  pname = "virby-vm";
  version = "0.1.0";

  pyproject = true;
  src = ./.;

  build-system = [ hatchling ];
  dependencies = [
    aiofiles
    vfkit
  ];

  pythonImportsCheck = [
    "vm_runner"
    "vm_runner.cli"
    "vm_runner.config"
    "vm_runner.constants"
    "vm_runner.exceptions"
    "vm_runner.ip_discovery"
    "vm_runner.runner"
    "vm_runner.ssh"
  ];

  meta = with lib; {
    description = "Vfkit-based VM runner for Virby, with automatic IP discovery and lifecycle management";
    homepage = "https://github.com/quinneden/virby-nix-darwin";
    license = licenses.mit;
    platforms = platforms.darwin;
  };
}
