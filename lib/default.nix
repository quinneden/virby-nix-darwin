# Library for shared constants and helper functions for Virby
{ lib }:

let
  constants = import ./constants.nix;
  helpers = import ./helpers.nix { inherit lib; };
in

{
  inherit constants helpers;
}
