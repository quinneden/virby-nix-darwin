{
  bash,
  commitizen,
  git,
  writeShellApplication,
}:

writeShellApplication {
  name = "bump-version";

  runtimeInputs = [
    bash
    commitizen
    git
  ];

  text = ''
    bash ${./bump-version.sh} "$@"
  '';
}
