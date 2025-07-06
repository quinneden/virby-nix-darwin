# Constants for the module
let
  vmHostName = "virby-vm";
  vmUser = "builder";
  sshHostPrivateKeyFileName = "ssh_host_ed25519_key";
  sshHostPublicKeyFileName = sshHostPrivateKeyFileName + ".pub";
  sshUserPrivateKeyFileName = "ssh_user_ed25519_key";
  sshUserPublicKeyFileName = sshUserPrivateKeyFileName + ".pub";
in
{
  inherit
    vmHostName
    vmUser
    sshHostPrivateKeyFileName
    sshHostPublicKeyFileName
    sshUserPrivateKeyFileName
    sshUserPublicKeyFileName
    ;
}
