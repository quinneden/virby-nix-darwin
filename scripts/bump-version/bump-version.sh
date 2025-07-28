#  Don't run this script directly.
#  Use:
#     `nix run .#bump-version -- {package} [options]`
#
#  This script bumps the version of the package specified by $1. Currently, the
#  only valid option is `vm-runner`.

set -eo pipefail

show_help() {
  echo "Bump the version of the vm-runner package" >&2
  echo >&2
  echo "Usage:" >&2
  echo "    bump-version {package} [-h|--help]" >&2
  echo >&2
  echo "Arguments:" >&2
  echo "    package    The package to bump the version of (currently, only accepts 'vm-runner')" >&2
  echo >&2
  echo "Options:" >&2
  echo "    -h, --help    Show this help message" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    vm-runner)
      package="$1"
      shift
      ;;
    *)
      echo "Error: Unknown option '$1'" >&2
      show_help
      exit 1
      ;;
  esac
done

if [[ $(git symbolic-ref --short HEAD) != "main" ]]; then
  echo "Error: script must be run from main branch" >&2
  exit 1
fi

uncommitted_changes=$(git diff --compact-summary)
if [[ -n "$uncommitted_changes" ]]; then
  echo "Error: there are uncommitted changes:" >&2
  echo "$uncommitted_changes" >&2
  exit 1
fi

git fetch "git@github.com:quinneden/virby-nix-darwin" main
unpushed_commits=$(git log --format=oneline origin/main..main)
if [[ -n "$unpushed_commits" ]]; then
  echo "Error: there are unpushed commits:" >&2
  echo "$unpushed_commits" >&2
  exit 1
fi

pushd pkgs/vm-runner &>/dev/null || exit 1

version=$(cz bump --major-version-zero --get-next)
cz bump \
  --major-version-zero \
  --tag-format="$package-v\$version" \
  --bump-message="chore($package): bump version to $version"

popd &>/dev/null || exit 1

read -rN1 -p "Push $package-v$version to remote? (y/N): " input
if [[ $input != [yY] ]]; then
  echo "To push the changes, run:"
  echo
  echo "    git push origin main $package-v$version"
  exit 0
else
  git push origin main "$package-v$version"
fi
