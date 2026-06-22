package vmprocess

import "time"

const (
	diffDiskFileName         = "diff.img"
	efiVariableStoreFileName = "efistore.nvram"
	ipDiscoveryTimeout       = 30 * time.Second
	serialLogFileName        = "serial.log"
	sshdKeysSharedDirName    = "vm_sshd_keys"
	sshReadyTimeout          = 30 * time.Second
)
