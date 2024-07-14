#!/usr/bin/env sh
# shellcheck shell=sh # POSIX

# This script installs Klipper3D on an Debian 12

set -e # Exit on false return


srcDir="$(git rev-parse --show-toplevel)"

# Exit trap
die() { printf "FATAL: %s\n" "$2"; exit 1 ;}

# Check for bare repo
[ "$(git rev-parse --is-bare-repository)" != "true" ] || die 1 "This script is NOT designed to run outside of the Klipper3D repository" 

PYTHONDIR="$HOME/klippy-env"
SYSTEMDDIR="/etc/systemd/system"
klipperUser="$USER"
# shellcheck disable=SC2034 # Keep this available in case it's ever needed
klipperGroup="$klipperUser"

# Step 1: Install system packages
install_packages() {
    # Packages for python cffi
    pkgsList="$pkgsList virtualenv python-dev-is-python3 libffi-dev build-essential"
    # kconfig requirements
    pkgsList="$pkgsList libncurses-dev"
    # hub-ctrl
    pkgsList="$pkgsList libusb-dev"
    # AVR chip installation and building
    pkgsList="$pkgsList avrdude gcc-avr binutils-avr avr-libc"
    # ARM chip installation and building
    pkgsList="$pkgsList stm32flash libnewlib-arm-none-eabi"
    pkgsList="$pkgsList gcc-arm-none-eabi binutils-arm-none-eabi pkg-config"
    # Working with the repository
    pkgsList="$pkgsList git"

    # Update system package info
    report_status "Running apt-get update..."
    sudo apt-get update

    # Install desired packages
    report_status "Installing packages..."

    # shellcheck disable=SC2086 # We expect the word splitting
    sudo apt-get install --yes $pkgsList
}

# Step 2: Create python virtual environment
create_virtualenv() {
    report_status "Updating python virtual environment..."

    # Create virtualenv if it doesn't already exist
    [ ! -d "$PYTHONDIR" ] && virtualenv -p python3 "$PYTHONDIR"

    # Install/update dependencies
    "$PYTHONDIR/bin/pip" install -r "$srcDir/scripts/klippy-requirements.txt"
}

# Step 3: Install startup script
install_script() {
# Create systemd service file
    klipperLog=/tmp/klippy.log
    report_status "Installing system start script..."
    sudo /bin/sh -c "cat > $SYSTEMDDIR/klipper.service" << EOF
#Systemd service file for klipper
[Unit]
Description=Starts klipper on startup
After=network.target

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=$klipperUser
RemainAfterExit=yes
ExecStart=$PYTHONDIR/bin/python $srcDir/klippy/klippy.py $HOME/printer.cfg -l $klipperLog
Restart=always
RestartSec=10
EOF
# Use systemctl to enable the klipper systemd service script
    sudo systemctl enable klipper.service
}

# Step 4: Start host software
start_software() {
    report_status "Launching Klipper host software..."
    sudo systemctl start klipper
}

# Helper functions
report_status() {
    printf "\n\n###### %s" "$1"
}

verify_ready() {
    [ "$(id -u)" != 0 ] || die 3 "This script must NOT run as root"
}

# Run installation steps defined above
verify_ready
install_packages
create_virtualenv
install_script
start_software
