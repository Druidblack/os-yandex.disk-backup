#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run as root' >&2; exit 1; fi
DST=/usr/local/opnsense
MANIFEST="$DST/scripts/OPNsense/YandexBackup/installed-files.txt"
if [ ! -f "$MANIFEST" ]; then
    echo 'Installation manifest not found; refusing blind removal' >&2
    exit 1
fi
# This does not delete /conf/config.xml, secrets, history, or cron jobs.
while IFS= read -r path; do
    case "$path" in
        "$DST"/mvc/app/controllers/OPNsense/YandexBackup/*|\
        "$DST"/mvc/app/models/OPNsense/YandexBackup/*|\
        "$DST"/mvc/app/views/OPNsense/YandexBackup/*|\
        "$DST"/mvc/app/library/OPNsense/Backup/YandexDisk.php|\
        "$DST"/service/conf/actions.d/actions_yandexbackup.conf|\
        "$DST"/scripts/OPNsense/YandexBackup/*)
            rm -f "$path" ;;
        *) echo "Refusing unexpected manifest path: $path" >&2; exit 1 ;;
    esac
done < "$MANIFEST"
rm -f "$DST/mvc/app/models/OPNsense/YandexBackup/Menu/Menu.xml"
rm -f "$MANIFEST"
rm -f /tmp/opnsense_menu_cache.xml
service configd restart
echo 'Plugin files removed. Remove the Yandex Disk Backup job from System -> Settings -> Cron.'
echo 'Stored configuration and /conf/yandexbackup history retained.'
