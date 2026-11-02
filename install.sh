#!/bin/sh
# os-yandex-backup 0.1.6: native Backups provider for OPNsense 26.7.
set -eu
BASE=$(CDPATH= cd "$(dirname "$0")" && pwd)
SRC="$BASE/src/opnsense"
DST=/usr/local/opnsense
STATE=/conf/yandexbackup
MANIFEST="$DST/scripts/OPNsense/YandexBackup/installed-files.txt"

if [ "$(id -u)" -ne 0 ]; then
    echo 'ERROR: run as root' >&2
    exit 1
fi
if [ ! -f /conf/config.xml ] || [ ! -d "$DST/mvc/app" ] || [ ! -x /usr/local/bin/python3 ]; then
    echo 'ERROR: this does not look like a supported OPNsense installation' >&2
    exit 1
fi
if [ ! -f "$SRC/mvc/app/library/OPNsense/Backup/YandexDisk.php" ]; then
    echo 'ERROR: native backup provider is missing from this archive' >&2
    exit 1
fi

umask 077
mkdir -p "$STATE" "$DST/scripts/OPNsense/YandexBackup"
chmod 700 "$STATE"
STAMP=$(date +%Y%m%d-%H%M%S)
cp -p /conf/config.xml "$STATE/config-before-yandexbackup-v016-$STAMP.xml"
chmod 600 "$STATE/config-before-yandexbackup-v016-$STAMP.xml"

echo 'Installing Yandex Disk Backup v0.1.6 (native OPNsense Backups provider)...'
FILES=$(mktemp /tmp/os-yandex-backup-files.XXXXXXXX)
trap 'rm -f "$FILES"' EXIT HUP INT TERM
find "$SRC" -type f ! -name '*.pyc' ! -name '*.pyo' > "$FILES"
while IFS= read -r from; do
    rel=${from#"$SRC"/}
    case "$rel" in
        mvc/app/*|service/conf/actions.d/actions_yandexbackup.conf|scripts/OPNsense/YandexBackup/*) ;;
        *) echo "ERROR: unexpected source path $rel" >&2; exit 1 ;;
    esac
    to="$DST/$rel"
    mkdir -p "$(dirname "$to")"
    case "$from" in
        *.py) install -m 0750 "$from" "$to" ;;
        *) install -m 0644 "$from" "$to" ;;
    esac
done < "$FILES"
# Old 0.1.0 registered an independent menu item. Native 0.1.3 is embedded
# in /diag_backup.php by BackupFactory, so remove only the obsolete menu file.
rm -f "$DST/mvc/app/models/OPNsense/YandexBackup/Menu/Menu.xml"

sed "s|^$SRC/|$DST/|" "$FILES" > "$MANIFEST"
chmod 600 "$MANIFEST"
chmod 700 "$DST/scripts/OPNsense/YandexBackup"
# On OPNsense the UI menu cache is stored here. Do not restart web UI.
rm -f /tmp/opnsense_menu_cache.xml
service configd restart

echo 'Installation finished. Existing Yandex OAuth, folder, retention settings and history were kept.'
echo 'New backups are plain XML. Old .ydenc backups are not deleted or converted.'
echo 'Open System -> Configuration -> Backups; scroll down to Yandex Disk.'
echo 'An additional advanced UI is available at /ui/yandexbackup/index.'
echo 'Check: configctl yandexbackup status'
