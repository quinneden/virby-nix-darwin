# Helper functions for the Virby Nix-darwin module
{ lib }:

let
  ESC = builtins.fromJSON ''"\u001b"'';
  GREEN = "${ESC}[32m";
  RED = "${ESC}[31m";
  RESET = "${ESC}[0m";

  logInfo = "printf >&2 \"[$(date '+%Y-%m-%d %H:%M:%S')] ${GREEN}INFO:${RESET} %s\n\"";
  logError = "printf >&2 \"[$(date '+%Y-%m-%d %H:%M:%S')] ${RED}ERROR:${RESET} %s\n\"";

  setupLogFunctions = ''
    logInfo() {
      echo -e "${GREEN}[virby]${RESET} $*" >&2
    }

    logError() {
      echo -e "${RED}[virby]${RESET} $*" >&2
    }
  '';

  parseMemoryString =
    with lib;
    s:
    let
      parts = splitStringBy (
        prev: curr: match "[0-9]" prev != null && match "[aA-zZ]" curr != null
      ) true s;
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
    if mib < 1024 then
      throw "The Virby VM requires at least 1024 MiB of memory, got: ${toString mib} MiB"
    else
      mib;
in

{
  inherit
    logError
    logInfo
    setupLogFunctions
    parseMemoryString
    ;
}
