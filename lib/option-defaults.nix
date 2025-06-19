let
  debug = false;
  extraConfig = { };

  onDemand = {
    enable = false;
    ttl = 180;
  };

  rosetta = {
    enable = false;
  };
in
{
  inherit
    debug
    extraConfig
    onDemand
    rosetta
    ;
}
