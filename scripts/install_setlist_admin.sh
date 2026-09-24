#!/bin/sh
# Installs the optional setlist-admin companion app (web UI for the
# library USB and WiFi -- SETLIST_ADMIN_SPECIFICATION.md).
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
#   sh scripts/install_setlist_admin.sh <usb-uuid>
#
# <usb-uuid> is the same UUID already used by pedal-core.service's
# --usb-uuid (systemd/README.md section 3) -- this app reads/writes the
# same library USB, so it needs the same identifier.

set -e

USB_UUID="$1"
if [ -z "$USB_UUID" ]; then
  echo "Usage: sh scripts/install_setlist_admin.sh <usb-uuid>" >&2
  echo "(the same UUID pedal-core.service's --usb-uuid already uses)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURRENT_USER="$(whoami)"

echo "Installing setlist-admin for user '$CURRENT_USER', repo at $REPO_ROOT, USB UUID $USB_UUID"

for unit in setlist-admin.service setlist-network-watchdog.service; do
  sed \
    -e "s#<YOUR_USER>#$CURRENT_USER#g" \
    -e "s#<YOUR_USB_UUID>#$USB_UUID#g" \
    -e "s#/home/$CURRENT_USER/chocolatepi#$REPO_ROOT#g" \
    "$REPO_ROOT/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
  echo "Installed /etc/systemd/system/$unit"
done

sudo systemctl daemon-reload

# Only the watchdog runs continuously from boot -- setlist-admin.service
# itself is started/stopped by the watchdog based on connectivity
# (section 5, step 4), deliberately never `enable`d directly.
sudo systemctl enable --now setlist-network-watchdog.service

echo ""
echo "Installed. setlist-network-watchdog.service is now running and will"
echo "start setlist-admin.service automatically once there's a usable IP."
echo ""
echo "Check status with:"
echo "  sudo systemctl status setlist-network-watchdog"
echo "  journalctl -u setlist-network-watchdog -f"
echo ""
echo "Don't forget to re-enable the read-only root overlay if you"
echo "disabled it to run this install (systemd/README.md section 4)."
