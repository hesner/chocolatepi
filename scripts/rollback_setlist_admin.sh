#!/bin/sh
# Rolls setlist-admin back out, per SETLIST_ADMIN_SPECIFICATION.md
# section 11: stops and disables both new services, removes their unit
# files, and reverts the code checkout to the last known-good tag from
# before this feature existed. pedal-core.service is never touched --
# it keeps running throughout, confirmed by this project's own test plan
# before this script is trusted for real use.
#
# Requires the read-only root overlay to be temporarily disabled first,
# same as installing (systemd/README.md section 4) -- the unit files
# being removed live under the overlaid /etc/systemd/system.
#
# Usage (from the repo root, on the Pi):
#   sh scripts/rollback_setlist_admin.sh [--purge]
#
# --purge also deletes .setlist-admin/ from the library USB (the PIN
# hash and encrypted WiFi credentials) -- omit it to keep that in place
# so a future reinstall doesn't need reconfiguring from scratch.

set -e

PURGE=0
if [ "$1" = "--purge" ]; then
  PURGE=1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="stable-pre-setlist-admin"

echo "Rolling back setlist-admin..."

sudo systemctl disable --now setlist-admin.service 2>/dev/null || true
sudo systemctl disable --now setlist-network-watchdog.service 2>/dev/null || true
echo "Stopped and disabled both services."

sudo rm -f /etc/systemd/system/setlist-admin.service
sudo rm -f /etc/systemd/system/setlist-network-watchdog.service
sudo systemctl daemon-reload
echo "Removed unit files."

cd "$REPO_ROOT"
git checkout "$TAG"
echo "Checked out $TAG."

if [ "$PURGE" = "1" ]; then
  echo "Purging .setlist-admin/ from the library USB..."
  sudo mount -o remount,rw /media/usb
  rm -rf /media/usb/.setlist-admin
  sudo mount -o remount,ro /media/usb
  echo "Purged."
fi

echo ""
echo "Rollback complete. pedal-core.service was never stopped or"
echo "restarted by this script -- confirm with:"
echo "  systemctl is-active pedal-core.service"
echo ""
echo "Don't forget to re-enable the read-only root overlay if you"
echo "disabled it to run this (systemd/README.md section 4)."
