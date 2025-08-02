# Helper functions for the Virby Nix-darwin module
{ lib }:

let
  ESC = builtins.fromJSON ''"\u001b"'';
  GREEN = "${ESC}[32m";
  RED = "${ESC}[31m";
  RESET = "${ESC}[0m";

  doppelganger =
    f:
    let
      swap = f: lib.replaceStrings [ "darwin" ] [ "linux" ] f;
    in
    if (lib.isList f) then map (l: swap l) f else swap f;

  logError = "printf \"[$(date '+%Y-%m-%d %H:%M:%S')] ${RED}ERROR:${RESET} %s\n\"";
  logInfo = "printf \"[$(date '+%Y-%m-%d %H:%M:%S')] ${GREEN}INFO:${RESET} %s\n\"";

  parseMemoryMiB =
    with lib;
    let
      validateMin =
        mib:
        if mib < 1024 then
          throw "The Virby VM requires at least 1024 MiB of memory, got: ${toString mib} MiB"
        else
          mib;
    in
    mem:
    if isString mem then
      let
        parts = splitStringBy (
          prev: curr: match "[0-9]" prev != null && match "[aA-zZ]" curr != null
        ) true mem;
        num = elemAt parts 0;
        suffix =
          if (length parts > 1) then
            elemAt parts 1
          else
            throw "memory string must contain a suffix, e.g. `4096MiB`";
        mib =
          if suffix == "GiB" || suffix == "G" then
            (toInt num) * 1024
          else if suffix == "MiB" || suffix == "M" then
            toInt num
          else
            throw "unsupported memory format: ${suffix}";
      in
      validateMin mib
    else
      let
        mib = mem;
      in
      validateMin mib;

  setupLogFunctions = ''
    logInfo() {
      echo -e "${GREEN}[virby]${RESET} $*" >&2
    }
    logError() {
      echo -e "${RED}[virby]${RESET} $*" >&2
    }
  '';

  toScreamingSnakeCase =
    with lib;
    s:
    let
      isUpper = c: match "[A-Z]" c != null;
      chars = stringToCharacters s;
    in
    concatStrings (
      map (
        c:
        if (isUpper c && c != elemAt chars 0) then
          "_" + c
        else if c == "-" then
          "_"
        else
          toUpper c
      ) chars
    );
in

{
  inherit
    doppelganger
    logError
    logInfo
    parseMemoryMiB
    setupLogFunctions
    toScreamingSnakeCase
    ;
}
