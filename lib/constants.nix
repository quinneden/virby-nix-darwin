let
  name = "virby";
  sshHostPrivateKeyFileName = "ssh_host_ed25519_key";
  sshHostPublicKeyFileName = sshHostPrivateKeyFileName + ".pub";
  sshUserPrivateKeyFileName = "ssh_user_ed25519_key";
  sshUserPublicKeyFileName = sshUserPrivateKeyFileName + ".pub";
  vmHostName = "virby-vm";
  vmUser = "builder";
in
{
  inherit
    name
    sshHostPrivateKeyFileName
    sshHostPublicKeyFileName
    sshUserPrivateKeyFileName
    sshUserPublicKeyFileName
    vmHostName
    vmUser
    ;
}
