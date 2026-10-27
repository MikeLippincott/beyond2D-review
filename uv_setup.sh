#!/bin/bash

# resolve the project root from this file's location so the script works when
# run or sourced from any directory
git_root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
UVR_TOML="$git_root/uvr.toml"

ENV_PATH="$git_root/.venv"


if [[ -e "$ENV_PATH" ]]; then
    echo "Using existing virtual environment at $ENV_PATH"
else
    mkdir -p "$ENV_PATH"
    echo "Created virtual environment directory at $ENV_PATH"
fi

# run twice to ensure we are in a clean environment
# and not accidentally using an existing one
# try but will not fail if not in a conda environment
loops=2
for _ in $(seq 1 $loops); do
    if command -v conda >/dev/null 2>&1; then
        conda deactivate >/dev/null 2>&1 || true
    fi
    deactivate >/dev/null 2>&1 || true
done
unset VIRTUAL_ENV

rm -rf "$ENV_PATH"

uv venv --project "$git_root" "$ENV_PATH"
uv sync --project "$git_root"

# IRkernel's installspec and the kernelspec lookup below both shell out to
# jupyter, so use the one installed in this environment
export PATH="$ENV_PATH/bin:$PATH"


echo "Virtual environment setup complete. To activate it, run:"
echo "source $ENV_PATH/bin/activate"

# set up uvr
echo "Setting up uvr..."
# check if r version is installed and meets the requirement
# parse this from the uvr.toml file
R_VERSION_REQUIRED=$(grep -m1 -E '^r_version[[:space:]]*=' "$UVR_TOML" | grep -oE '[0-9]+(\.[0-9]+)*' | head -n1)
uvr r install "$R_VERSION_REQUIRED"
if [[ -z "$R_VERSION_REQUIRED" ]]; then
    echo "Error: no valid r_version found in $UVR_TOML (expected e.g. r_version = \">=4.3.0\")."
fi

if [[ -d "$git_root/.uvr" ]]; then
    rm -rf "$git_root/.uvr"
fi
# reinstall the locked R packages (including IRkernel) into the fresh library
(cd "$git_root" && uvr sync)


# resolve the project's R through uvr (not a developer-specific path)
# mktemp --suffix is GNU-only (fails on macOS), so make a temp dir instead
R_BIN_DIR=$(mktemp -d)
R_BIN_SCRIPT="$R_BIN_DIR/r_bin.R"
printf '%s\n' 'cat(file.path(R.home("bin"), "R"), "\n")' > "$R_BIN_SCRIPT"
R_BIN=$(cd "$git_root" && uvr run "$R_BIN_SCRIPT" 2>/dev/null | tail -n1 | xargs)
rm -rf "$R_BIN_DIR"
if [[ -z "$R_BIN" || ! -x "$R_BIN" ]]; then
    R_BIN=$(command -v R || true)
fi
if [[ -z "$R_BIN" || ! -x "$R_BIN" ]]; then
    echo "Error: no R executable found (checked uvr and PATH)."
fi
R_VERSION_INSTALLED=$("$R_BIN" --version | head -n 1 | awk '{print $3}')
if [[ $(printf '%s\n' "$R_VERSION_REQUIRED" "$R_VERSION_INSTALLED" | sort -V | head -n1) != "$R_VERSION_REQUIRED" ]]; then
    echo "R version $R_VERSION_REQUIRED or higher is required. Installed version is $R_VERSION_INSTALLED."
    echo "Please install the required R version."
fi

echo "Setting up Jupyter kernel for the virtual environment..."

ENV_NAME=$(grep -m1 -E '^name[[:space:]]*=' "$UVR_TOML" | sed -E 's/^name[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')

INSTALL_KERNEL_DIR=$(mktemp -d)
INSTALL_KERNEL_SCRIPT="$INSTALL_KERNEL_DIR/install_kernel.R"
trap 'rm -rf "$INSTALL_KERNEL_DIR"' EXIT
cat > "$INSTALL_KERNEL_SCRIPT" << EOF
IRkernel::installspec(name = "$ENV_NAME", displayname = "$ENV_NAME")
EOF

(cd "$git_root" && uvr run "$INSTALL_KERNEL_SCRIPT")
rm -rf "$INSTALL_KERNEL_DIR"

KERNEL_DIR=$(jupyter kernelspec list | awk -v name="$ENV_NAME" 'tolower($1) == tolower(name) {print $2}')

if [[ -z "$KERNEL_DIR" ]]; then
    echo "Could not find installed kernelspec matching '$ENV_NAME'"
    jupyter kernelspec list
    exit 1
fi

PROJECT_LIB="$git_root/.uvr/library"

cat > "$KERNEL_DIR/kernel-wrapper.sh" << EOF
#!/bin/bash
export R_LIBS="$PROJECT_LIB"
exec "$R_BIN" --slave -e 'IRkernel::main()' --args "\$1"
EOF
chmod +x "$KERNEL_DIR/kernel-wrapper.sh"

python3 - "$KERNEL_DIR/kernel.json" "$KERNEL_DIR/kernel-wrapper.sh" << 'PYEOF'
import json, sys
path, wrapper = sys.argv[1], sys.argv[2]
with open(path) as f:
    spec = json.load(f)
spec["argv"] = [wrapper, "{connection_file}"]
spec.pop("env", None)
with open(path, "w") as f:
    json.dump(spec, f, indent=2)
PYEOF

echo "Final kernel.json:"
cat "$KERNEL_DIR/kernel.json"
echo "Wrapper script:"
cat "$KERNEL_DIR/kernel-wrapper.sh"
