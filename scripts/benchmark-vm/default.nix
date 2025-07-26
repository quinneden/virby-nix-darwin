{
  bash,
  curl,
  hyperfine,
  writeShellApplication,
}:

writeShellApplication {
  name = "benchmark-virby-vm";

  runtimeInputs = [
    bash
    curl
    hyperfine
  ];

  text = ''
    bash ${./benchmark-vm.sh} "$@"
  '';
}
