## vm-runner-v0.2.0 (2025-07-27)

### Feat

- add bump-version flake app
- **vm-runner**: add support for VM pause/resume operations
- add centralized signal manager for VM shutdown coordination
- add circuit breaker pattern for VM operations
- add vfkit API client for virtual machine management
- add benchmark-vm flake application
- **vm-runner**: add early signal handling and orphaned process cleanup

### Fix

- **bump-version**: pass positional args to script
- **bump-version**: fix cz commands
- rewrap comment in code block
- **flake**: fix path to benchmark-vm script
- **vm-runner,module**: add on-demand to json config file
- **vm-runner**: optimize VM startup performance
- **module**: initialize `NEEDS_GENERATE_SSH_KEYS` variable before logic
- **flake**: change `nixpkgs` branch
- comment out logind auto-poweroff config and add vm pause/resume

### Refactor

- **module**: refactor ssh keygen logic
- **vm-runner**: remove unneccessary `debug_file_descriptors`

## vm-runner-v0.1.0 (2025-07-27)

### BREAKING CHANGE

- The `rosetta.enable` option has been removed and replaced with
`rosetta`. Update your configuration accordingly.

### Feat

- add CI workflow
- **vm-runner**: add socket activation with tcp port forwarding
- **vm-runner**: add comprehensive Python VM runner implementation
- add python VM runner package

### Fix

- **vm-runner**: refactor code structure
- **module**: fix option type for
- **vm-image**: fix `virtualization.rosetta.enable` setting
- **module,vm-runner**: change option `rosetta.enable` to `rosetta`
- **vm-runner**: fix SSH in always-on mode
- **module**: fix default values for `onDemand` and `rosetta` options
- direct both logInfo and logError to stdout
- **module**: compare store path of source image instead of hash
- remove gvproxy from dev-shell packages
- change package name to `virby-vm-runner` in pkgs/vm-runner/default.nix
- `pkgs.hostPlatform.system` -> `pkgs.system` in virby/default.nix
- remove redundant `pkgs` reference in `default.nix`
- **docs**: add information about binary-cache to README
- use nix in .envrc
- update reference to vm-runner executable in darwin module
- **pkgs/vm-runner**: Fix SSH connection issues with VM runner

### Refactor

- **vm-image**: simplify install-sshd-keys service
- update functions in flake.nix
- add `default` attr for vm-runner, lib.replaceString -> lib.replaceStrings
- remove `lib/option-defaults.nix`, cleanup code
- **module,vm-runner**: generate python constants from nix code
- **Justfile**: add setup-test-working-directory
- include `layout_uv` in `.envrc` and update `pyproject.toml`
- update module and image configuration
- **vm-image**: change kernel flag
