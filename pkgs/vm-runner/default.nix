{
  lib,
  aiofiles,
  buildPythonPackage,
  hatchling,
  vfkit,
}:

buildPythonPackage {
  pname = "virby-vm-runner";
  version = "0.1.0";

  pyproject = true;
  src = ./.;

  build-system = [ hatchling ];
  dependencies = [
    aiofiles
    vfkit
  ];

  pythonImportsCheck = [
    "virby_vm_runner"
    "virby_vm_runner.cli"
    "virby_vm_runner.config"
    "virby_vm_runner.constants"
    "virby_vm_runner.exceptions"
    "virby_vm_runner.ip_discovery"
    "virby_vm_runner.runner"
    "virby_vm_runner.ssh"
  ];

  meta = with lib; {
    description = "Vfkit-based VM runner for Virby, with automatic IP discovery and lifecycle management";
    homepage = "https://github.com/quinneden/virby-nix-darwin";
    license = licenses.mit;
    platforms = platforms.darwin;
    mainProgram = "virby-vm";
  };
}
