# os-yandex.disk-backup

Плагин OPNsense для резервного копирования настроек на Яндекс Диск.

**Совместимость:** для OPNsense **26.7.x**

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


## Получение OAuth-токена Яндекс.Диска

1. Откройте [Яндекс OAuth](https://oauth.yandex.ru/) и нажмите **Создать приложение**
2. Выберите **Для доступа к API или отладки**. Введите название приложения, например `OPNsense Yandex Backup`
3. В разделе **Доступ к данным** найдите **Яндекс.Диск** и предоставьте **оба** разрешения:

   - `cloud_api:disk.read` — чтение файлов и папок на Диске;
   - `cloud_api:disk.write` — создание папок, загрузка и удаление старых резервных копий.

4. Создайте приложение. Скопируйте **ClientID** из его настроек.
5. В браузере, где выполнен вход в нужный аккаунт Яндекса, откройте ссылку, заменив `YOUR_CLIENT_ID` идентификатором приложения:

   ```text
   https://oauth.yandex.ru/authorize?response_type=token&client_id=YOUR_CLIENT_ID
   ```

6. Подтвердите запрос на доступ. Скопируйте значение `access_token` с открывшейся страницы либо из адреса после `#access_token=`. **Не копируйте всю ссылку**: в плагин нужно вставить только сам токен.

## Автоматическое резервное копирование

1. Откройте **System → Settings → Cron**.
2. Нажмите **Add**.
3. В поле команды выберите **Yandex Disk Backup**.
4. Установите нужное расписание (например, ежедневно ночью).
5. Сохраните задание и примените изменения.


## Настройка плагина

В **System → Configuration → Backups → Yandex Disk** укажите:

| Параметр | Описание |
|---|---|
| **Enable Yandex Disk backups** | Включить создание резервных копий |
| **Yandex OAuth token** | OAuth-токен с правами чтения и записи |
| **Remote folder** | Папка на Яндекс.Диске, например `OPNsense-Backups` |
| **Backups to keep** | Число хранимых XML-копий (1–365) |

Нажмите **Setup/Test Yandex Disk**. Плагин сохранит настройки, и **сразу создаст проверочную резервную копию**.

Когда токен сохранён, поле отображается скрытыми символами. Чтобы заменить токен, выделите маску и вставьте новый. При повторном сохранении с неизменённой маской ранее сохранённый токен остаётся действующим.

Дополнительный интерфейс с проверками, кнопкой **Backup now**, списком файлов и историей доступен по адресу:

```text
https://IP-АДРЕС-OPNSENSE/ui/yandexbackup/index
```
