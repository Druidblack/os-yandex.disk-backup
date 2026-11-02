<?php

namespace OPNsense\YandexBackup\Api;

use OPNsense\Base\ApiMutableModelControllerBase;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelClass = 'OPNsense\YandexBackup\General';
    protected static $internalModelName = 'yandexbackup';
}
