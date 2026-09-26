#!/bin/sh
# Installs the optional setlist-admin companion app (web UI for the
# library USB, reachable by plugging a phone into the Pi over USB --
# SETLIST_ADMIN_USB_SPECIFICATION.md).
#
# Deliberately NOT part of the base pedal-core install (systemd/README.md
# sections 0-4): the base pedal system works identically whether or not
# this is ever run (specification section 11). Run this manually, once,
# only if you actually want setlist-admin.
#
# Requires the read-only root overlay to be temporarily disabled first
# (same requirement as installing pedal-core.service itself) --
# `sudo raspi-config nonint do_overlayfs 1 && sudo reboot`, run this,
# then re-enable it (systemd/README.md section 4).
#
# Usage (from the repo root, on the Pi):
#   sh scripts/install_setlist_admin.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURRENT_USER="$(whoami)"

echo "Installing setlist-admin for user '$CURRENT_USER', repo at $REPO_ROOT"

for unit in setlist-admin.service usb-tether-watchdog.service; do
  sed \
    -e "s#<YOUR_USER>#$CURRENT_USER#g" \
    -e "s#/home/$CURRENT_USER/chocolatepi#$REPO_ROOT#g" \
    "$REPO_ROOT/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
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
echo "cable plugged in -- SETLIST_ADMIN_USB_SPECIFICATION.md section 4)."
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
