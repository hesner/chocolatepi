#!/bin/sh
# Installs the optional setlist-admin (USB) expansion -- a web UI for
# the library USB, reachable by plugging a phone into the Pi over USB.
# See ../SPECIFICATION.md and ../../README.md for what an "expansion"
# is in this project.
#
# Deliberately NOT part of the base pedal-core install (systemd/README.md
# sections 0-4): the base pedal system works identically whether or not
# this expansion is ever installed (SPECIFICATION.md section 11). Run
# this manually, once, only if you actually want it.
#
# Requires the read-only root overlay to be temporarily disabled first
# (same requirement as installing pedal-core.service itself) --
# `sudo raspi-config nonint do_overlayfs 1 && sudo reboot`, run this,
# then re-enable it (systemd/README.md section 4).
#
# Usage (from anywhere, on the Pi, inside a checkout of this repo):
#   sh expansions/setlist-admin-usb/scripts/install.sh

set -e

EXPANSION_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURRENT_USER="$(whoami)"

echo "Installing the setlist-admin-usb expansion for user '$CURRENT_USER', at $EXPANSION_ROOT"

for unit in setlist-admin.service usb-tether-watchdog.service; do
  sed \
    -e "s#<YOUR_USER>#$CURRENT_USER#g" \
    -e "s#/home/$CURRENT_USER/chocolatepi/expansions/setlist-admin-usb#$EXPANSION_ROOT#g" \
    "$EXPANSION_ROOT/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
  echo "Installed /etc/systemd/system/$unit"
done

sudo systemctl daemon-reload

# Only the watchdog runs continuously from boot -- setlist-admin.service
# itself is started/stopped by the watchdog based on whether a phone is
# currently tethered over USB (section 4c), deliberately never
# `enable`d directly.
sudo systemctl enable --now usb-tether-watchdog.service

echo ""
echo "Installed. usb-tether-watchdog.service is now running and will"
echo "start setlist-admin.service automatically once a phone is tethered"
echo "over USB (Android USB tethering, or iPhone Personal Hotspot with the"
echo "cable plugged in -- see ../SPECIFICATION.md section 4)."
echo ""
echo "If you plan to support iPhone, also run:"
echo "  sudo apt install -y usbmuxd"
echo ""
echo "Check status with:"
echo "  sudo systemctl status usb-tether-watchdog"
echo "  journalctl -u usb-tether-watchdog -f"
echo ""
echo "Don't forget to re-enable the read-only root overlay if you"
echo "disabled it to run this install (systemd/README.md section 4)."
