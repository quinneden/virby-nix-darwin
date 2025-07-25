#  Don't run this script directly.
#  Use:
#     `nix run .#benchmark-vm -- {subcommand} [options]`
#
#  This script benchmarks the performance of the Virby VM. It depends on a nix-darwin configuration
#  with `services.virby.enable = true`. In the future, I may add logic to setup a temporary VM and
#  mock launchd environment.
#
#  Currently, it is not possible to build derivations on a remote builder while specifying the `--rebuild`
#  flag (see: https://github.com/NixOS/nix/issues/10451), so, the workaround is to manually ssh into
#  the VM and run the `nix build` command instead.

set -eo pipefail

show_help() {
  echo "Benchmark the performance of the Virby VM"
  echo
  echo "Usage:"
  echo "    benchmark-vm {boot|build|help} [options]"
  echo
  echo "Subcommands:"
  echo "    boot                  Measure the time it takes to boot the VM from a cold start"
  echo "    build [DERIVATION]    Measure the time it takes to build a derivation on the VM (default: 'nixpkgs#hello')"
  echo "    help                  Show this help message"
  echo
  echo "Options:"
  echo "    -d, --output-dir DIRECTORY    Specify the output directory for the results (default: current directory)"
  echo "    -f, --format FORMAT           Specify the format in which the results will be exported (default: markdown)"
  echo "                                  Supported formats: asciidoc, csv, json, markdown, org"
  echo "    -h, --help                    Show this help message"
  echo "    -r, --runs RUNS               Specify the number of times to run the benchmark (default: 5)"
}

show_ssh_warning() {
  echo -e "${YELLOW}Warning: The script may be unable to connect to the VM via SSH. To ensure that you have the correct${RESET}" >&2
  echo -e "${YELLOW}permissions, either run the script as root, or in your Nix-darwin configuration, set:${RESET}" >&2
  echo >&2
  echo -e "${YELLOW}    services.virby.allowUserSsh = true${RESET}" >&2
  sleep 1
}
export -f show_ssh_warning

check_vm_is_started() {
  vm_state=$(curl -s http://localhost:31223/vm/state | jq -r '.state')
  [[ $vm_state == 'VirtualMachineStateRunning' ]] || return 1
}
export -f check_vm_is_started

stop_vm() {
  if ! curl -X POST -d '{"state":"Stop"}' http://localhost:31223/vm/state; then
    echo -e "${RED}Error: Failed to stop the VM${RESET}" >&2
    exit 1
  fi
}
export -f stop_vm

ssh_vm() {
  ssh virby-vm -- "${@:-true}"
}
export -f ssh_vm

run_benchmark() {
  local benchmark_type filename timestamp
  local args=()
  benchmark_type="$1"
  timestamp=$(date +%Y%m%d-%H%M%S)
  filename="${filename_prefix}-${benchmark_type}-${timestamp}.${filename_extension}"

  echo -e "${BOLD}Running benchmark:${RESET} ${benchmark_type}"
  echo -e "${BOLD}Export format:${RESET} ${export_format}"
  echo -e "${BOLD}Output file:${RESET} ${output_dir}/${filename}"
  echo -e "${BOLD}Runs:${RESET} ${runs}"
  echo

  args+=(
    "--style" "full"
    "--runs" "${runs}"
    "--export-${export_format}" "${output_dir}/${filename}"
  )

  if [[ $benchmark_type == 'boot' ]]; then
    args+=(
      "--setup" "check_vm_is_started || (ssh_vm; sleep 3)"
      "--prepare" "stop_vm; sleep 3"
      "ssh_vm"
    )
  elif [[ $benchmark_type == 'build' ]]; then
    args+=(
      "--warmup" "1"
      "--setup" "ssh_vm nix build --no-link $derivation"
      "ssh_vm nix build --no-link --rebuild $derivation"
    )
  fi

  if ! hyperfine "${args[@]}"; then
    if [[ -f ${output_dir}/${filename} && -z $(cat "${output_dir}/${filename}") ]]; then
      rm -f "${output_dir}/${filename}"
    fi

    show_ssh_warning
    exit 1
  fi
}

BOLD='\033[1m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
RESET='\033[0m'

filename_prefix="virby-vm-benchmark"

# Default values
command="show_help"
derivation="nixpkgs#hello"
export_format="markdown"
filename_extension="md"
output_dir="$PWD"
runs=5

# Check if the Launchd service plist file exists
if [[ ! -f /Library/LaunchDaemons/org.nixos.virbyd.plist ]]; then
  echo -e "${RED}Error: property list file for 'org.nixos.virbyd' not found.${RESET}" >&2
  echo -e "${RED}In your Nix-darwin configuration, set:${RESET}" >&2
  echo >&2
  echo -e "    ${RED}services.virby.enable = true;${RESET}" >&2
  echo -e "    ${RED}services.virby.allowUserSsh = true;${RESET}" >&2
  exit 1
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -h | --help | help)
      shift
      show_help
      exit 0
      ;;

    -d | --output-dir)
      shift
      if [[ -z $1 ]]; then
        echo -e "${RED}Error: argument requires 1 arg, but were given${RESET}" >&2
        exit 1
      elif [[ ! -d $1 ]]; then
        echo -e "${RED}Error: $1: does not exist, or is not a directory${RESET}" >&2
        exit 1
      fi
      output_dir="$1"
      shift
      ;;

    -f | --format)
      shift
      if [[ -z $1 ]]; then
        echo -e "${RED}Error: argument requires 1 arg, but 0 were given${RESET}" >&2
        exit 1
      fi
      case $1 in
        asciidoc)
          export_format="$1"
          filename_extension="adoc"
          ;;
        csv)
          export_format="$1"
          filename_extension="csv"
          ;;
        json)
          export_format="$1"
          filename_extension="json"
          ;;
        markdown)
          export_format="$1"
          filename_extension="md"
          ;;
        org)
          export_format="$1"
          filename_extension="org"
          ;;
        *)
          echo -e "${RED}Error: '$1' is not one of: asciidoc, csv, json, markdown, org${RESET}" >&2
          exit 1
          ;;
      esac
      shift
      ;;

    -r | --runs)
      shift
      if [[ -z $1 ]]; then
        echo -e "${RED}Error: argument requires 1 arg, but 0 were given${RESET}" >&2
        exit 1
      elif ! [[ $1 =~ ^[0-9]+$ ]]; then
        echo -e "${RED}Error: Invalid number of runs: $1${RESET}" >&2
        exit 1
      fi
      runs="$1"
      shift
      ;;

    boot)
      shift
      command="run_benchmark boot"
      ;;

    build)
      shift
      if [[ -n $1 && $1 != -* ]]; then
        if ! [[ $1 =~ ^[[:alnum:](.|/)]+(:|#).+ ]]; then
          echo -e "${RED}Error: Invalid derivation format: $1${RESET}" >&2
          exit 1
        fi
        derivation="$1"
        shift
      fi
      command="run_benchmark build"
      ;;

    *)
      echo -e "${RED}Error: Invalid argument: $1${RESET}";
      show_help
      exit 1
      ;;
  esac
done

# Run the benchmark command, or show help
eval "${command}"
