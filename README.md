# os-yandex.disk-backup

Плагин OPNsense для резервного копирования настроек на Яндекс Диск.

<img width="1575" height="313" alt="img" src="https://github.com/user-attachments/assets/0bb2d928-8122-4dfb-820a-1e5eafa7be21" />

# Установка

````
fetch -o - https://github.com/Druidblack/os-yandex.disk-backup/archive/refs/heads/master.tar.gz | tar -xzf - -C /tmp
sh /tmp/os-yandex.disk-backup-master/install.sh
````

или через git ```pkg install git```

```
git clone https://github.com/Druidblack/os-yandex.disk-backup /root/os-yandex.disk-backup
sh /root/os-yandex.disk-backup/install.sh                                   # install
cd /root/os-yandex.disk-backup && git pull && sh install.sh                 # update
```
 для удаления
 
 ```
sh uninstall.sh
```
