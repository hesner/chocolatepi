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

for unit in setlist-admin.service usb-tether-watchdog.service library-optimizer.service; do
  sed \
    -e "s#<YOUR_USER>#$CURRENT_USER#g" \
    -e "s#/home/$CURRENT_USER/chocolatepi/expansions/setlist-admin-usb#$EXPANSION_ROOT#g" \
    "$EXPANSION_ROOT/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
  echo "Installed /etc/systemd/system/$unit"
done

sudo systemctl daemon-reload

# The watchdog and the library optimizer both run continuously from
# boot, independent of whether a phone is tethered -- setlist-admin.service
# itself is started/stopped by the watchdog based on that (section 4c),
# deliberately never `enable`d directly. The optimizer specifically
# needs to outlive setlist-admin.service's own on/off cycles, since a
# queued "Optimize" job can take a very long time on this hardware
# (confirmed live, roughly 90 minutes for one problematic video) and
# must survive the phone that queued it disconnecting partway through.
sudo systemctl enable --now usb-tether-watchdog.service
sudo systemctl enable --now library-optimizer.service

echo ""
echo "Installed. usb-tether-watchdog.service is now running and will"
echo "start setlist-admin.service automatically once either condition is"
echo "true: a phone is tethered over USB (Android USB tethering, or"
echo "iPhone Personal Hotspot with the cable plugged in -- see"
echo "../SPECIFICATION.md section 4), or a USB WiFi dongle on the Pi is"
echo "connected to its own trusted home network (section 16, and"
echo "../USAGE.md's 'Reaching the app over WiFi')."
echo ""
echo "library-optimizer.service is also now running, independently of"
echo "whether a phone is tethered -- it processes any 'Optimize' job"
echo "queued from the app, even if the phone that queued it disconnects"
echo "before the job finishes (this can take a very long time on this"
echo "hardware)."
echo ""
echo "If you plan to support iPhone, also run:"
echo "  sudo apt install -y usbmuxd"
echo ""
echo "Check status with:"
echo "  sudo systemctl status usb-tether-watchdog"
echo "  journalctl -u usb-tether-watchdog -f"
echo "  sudo systemctl status library-optimizer"
echo "  journalctl -u library-optimizer -f"
echo ""
echo "Don't forget to re-enable the read-only root overlay if you"
echo "disabled it to run this install (systemd/README.md section 4)."
