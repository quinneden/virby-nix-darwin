"""
Variable constants for Virby

WARNING: This file's contents are overwritten as part of the nix build process. The values
here are just for testing without building the nix package. The actual values used in the
package are derived from _lib.constants, or ../../lib/constants.nix.
"""

WORKING_DIRECTORY = "/var/lib/virby"

# DHCP lease file location on macOS
DHCPD_LEASES_FILE_PATH = "/var/db/dhcpd_leases"

# VM configuration
VM_USER = "builder"
VM_HOST_NAME = "virby-vm"

# File names
SSH_HOST_PRIVATE_KEY_FILE_NAME = "ssh_host_ed25519_key"
SSH_HOST_PUBLIC_KEY_FILE_NAME = "ssh_host_ed25519_key.pub"
SSH_USER_PRIVATE_KEY_FILE_NAME = "ssh_user_ed25519_key"
SSH_USER_PUBLIC_KEY_FILE_NAME = "ssh_user_ed25519_key.pub"
SSHD_KEYS_SHARED_DIR_NAME = "vm_sshd_keys"
SSH_KNOWN_HOSTS_FILE_NAME = "ssh_known_hosts"

# VM runtime files
EFI_VARIABLE_STORE_FILE_NAME = "efistore.nvram"
BASE_DISK_FILE_NAME = "base.img"
DIFF_DISK_FILE_NAME = "diff.img"
SERIAL_LOG_FILE_NAME = "serial.log"
