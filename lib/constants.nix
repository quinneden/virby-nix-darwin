# Constants for the Virby Nix-darwin module
let
  baseDiskFileName = "base.img";
  dhcpdLeasesFilePath = "/var/db/dhcpd_leases";
  diffDiskFileName = "diff.img";
  efiVariableStoreFileName = "efistore.nvram";
  serialLogFileName = "serial.log";
  sshdKeysSharedDirName = "vm_sshd_keys";
  sshHostPrivateKeyFileName = "ssh_host_ed25519_key";
  sshHostPublicKeyFileName = sshHostPrivateKeyFileName + ".pub";
  sshKnownHostsFileName = "ssh_known_hosts";
  sshUserPrivateKeyFileName = "ssh_user_ed25519_key";
  sshUserPublicKeyFileName = sshUserPrivateKeyFileName + ".pub";
  vmHostName = "virby-vm";
  vmUser = "builder";
  workingDirectory = "/var/lib/virby";
in

{
  inherit
    baseDiskFileName
    dhcpdLeasesFilePath
    diffDiskFileName
    efiVariableStoreFileName
    serialLogFileName
    sshdKeysSharedDirName
    sshHostPrivateKeyFileName
    sshHostPublicKeyFileName
    sshKnownHostsFileName
    sshUserPrivateKeyFileName
    sshUserPublicKeyFileName
    vmHostName
    vmUser
    workingDirectory
    ;
}
