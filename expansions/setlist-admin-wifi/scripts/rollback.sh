#!/bin/sh
# Uninstalls the setlist-admin (WiFi) expansion, per ../SPECIFICATION.md
# section 11: stops and disables both services and removes their unit
# files. pedal-core.service is never touched -- it keeps running
# throughout, confirmed by this project's own test plan before this
# script is trusted for real use.
#
# Deliberately does NOT touch git history or check out any tag: an
# expansion's own source files (this whole expansions/setlist-admin-wifi/
# folder) are inert on disk once its systemd units are gone -- nothing
# runs them, nothing else in the repo depends on them existing. Doing a
# repo-wide `git checkout` here would also risk reverting an unrelated
# expansion (e.g. expansions/setlist-admin-usb/) if it was added in a
# later commit than this one's pre-install tag, which would break the
# "each expansion is independent" property the whole expansions/
# folder exists for.
#
# Requires the read-only root overlay to be temporarily disabled first,
# same as installing (systemd/README.md section 4) -- the unit files
# being removed live under the overlaid /etc/systemd/system.
#
# Usage (from anywhere, on the Pi, inside a checkout of this repo):
#   sh expansions/setlist-admin-wifi/scripts/rollback.sh [--purge]
#
# --purge also deletes .setlist-admin/ from the library USB (the PIN
# hash and encrypted WiFi credentials) -- omit it to keep that in place
# so a future reinstall doesn't need reconfiguring from scratch.

set -e

PURGE=0
if [ "$1" = "--purge" ]; then
  PURGE=1
fi

echo "Uninstalling the setlist-admin-wifi expansion..."

sudo systemctl disable --now setlist-admin.service 2>/dev/null || true
sudo systemctl disable --now setlist-network-watchdog.service 2>/dev/null || true
echo "Stopped and disabled both services."

sudo rm -f /etc/systemd/system/setlist-admin.service
sudo rm -f /etc/systemd/system/setlist-network-watchdog.service
sudo systemctl daemon-reload
echo "Removed unit files."

if [ "$PURGE" = "1" ]; then
  echo "Purging .setlist-admin/ from the library USB..."
  # Not `mount -o remount,rw` -- ntfs-3g (a FUSE filesystem) refuses
  # in-place remounts outright, confirmed against the real library USB.
  sudo umount /media/usb
  sudo mount -o rw /media/usb
  rm -rf /media/usb/.setlist-admin
  sudo umount /media/usb
  sudo mount -o ro /media/usb
  echo "Purged."
fi

echo ""
echo "Uninstall complete. pedal-core.service was never stopped or"
echo "restarted by this script -- confirm with:"
echo "  systemctl is-active pedal-core.service"
echo ""
echo "The expansion's own files are still on disk (harmless, inert --"
echo "nothing runs them with the services gone). Delete them too if you"
echo "want, or leave them for a future reinstall:"
echo "  rm -rf expansions/setlist-admin-wifi"
echo ""
echo "Don't forget to re-enable the read-only root overlay if you"
echo "disabled it to run this (systemd/README.md section 4)."
