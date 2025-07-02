{
  aiofiles,
  buildPythonPackage,
  hatchling,
  vfkit,
  lib,
}:

buildPythonPackage {
  pname = "vm-runner";
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
    "vm_runner.ip_discovery"
    "vm_runner.runner"
    "vm_runner.ssh"
  ];

  meta = with lib; {
    description = "Python package for running the virby-vm";
    homepage = "https://github.com/quinneden/virby-nix-darwin";
    license = licenses.mit;
    platforms = platforms.darwin;
  };
}
