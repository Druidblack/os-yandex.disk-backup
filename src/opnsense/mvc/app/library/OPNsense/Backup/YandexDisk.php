<?php
/**
 * Yandex Disk backup provider for the native OPNsense Configuration > Backups page.
 * OPNsense 26.7 BackupFactory discovers classes implementing IBackupProvider here.
 * Stores settings in the same MVC model used by os-yandex-backup 0.1.0.
 */

namespace OPNsense\Backup;

use OPNsense\Core\Config;
use OPNsense\Core\Backend;
use OPNsense\YandexBackup\General;

class YandexDisk implements IBackupProvider
{
    // Display-only placeholder. The actual OAuth token is never returned to the form.
    private const STORED_TOKEN_MASK = '********';

    private function model(): General
    {
        return new General();
    }

    public function getName()
    {
        return gettext('Yandex Disk');
    }

    public function getConfigurationFields()
    {
        $settings = $this->model()->general;
        return [
            [
                'name' => 'enabled', 'type' => 'checkbox',
                'label' => gettext('Enable Yandex Disk backups'),
                'help' => gettext('Setup/Test saves these settings and uploads a backup when enabled. Schedule the Yandex Disk Backup command under System > Settings > Cron.'),
                'value' => (string)$settings->enabled,
            ],
            [
                'name' => 'oauth_token', 'type' => 'password',
                'label' => gettext('Yandex OAuth token'),
                'help' => gettext('Leave it unchanged to retain the saved token, or select all and paste a replacement.'),
                'value' => $this->previousSecret('oauth_token') !== '' ? self::STORED_TOKEN_MASK : '',
            ],
            [
                'name' => 'remote_folder', 'type' => 'text',
                'label' => gettext('Remote folder'),
                'help' => gettext('Folder on Yandex.Disk it will be created automatically.'),
                'value' => (string)$settings->remote_folder ?: 'OPNsense-Backups',
            ],
            [
                'name' => 'retention', 'type' => 'text',
                'label' => gettext('Backups to keep'),
                'help' => gettext('Keep 1 to 365 backups for this firewall. Older backup files are removed only after a new upload has been verified.'),
                'value' => (string)$settings->retention ?: '30',
            ],
        ];
    }

    private function previousSecret(string $name): string
    {
        $root = Config::getInstance()->object();
        if (isset($root->OPNsense->yandexbackup->general->{$name})) {
            return (string)$root->OPNsense->yandexbackup->general->{$name};
        }
        return '';
    }

    private function booleanValue($value): string
    {
        return in_array(strtolower((string)$value), ['on', '1', 'yes', 'true'], true) ? '1' : '0';
    }

    /**
     * OPNsense 26.7 diag_backup.php reuses its POSTed $pconfig to render the
     * response after Setup/Test. Replace our submitted secret in that array,
     * otherwise the raw OAuth token would be included in the HTML value attr.
     * (Other backup providers' form fields are not touched.)
     */
    private function maskLegacyPostedToken(bool $stored): void
    {
        if (isset($GLOBALS['pconfig']) && is_array($GLOBALS['pconfig']) &&
            array_key_exists('YandexDisk_oauth_token', $GLOBALS['pconfig'])) {
            $GLOBALS['pconfig']['YandexDisk_oauth_token'] = $stored ? self::STORED_TOKEN_MASK : '';
        }
    }

    public function setConfiguration($conf)
    {
        $errors = [];
        $enabled = $this->booleanValue($conf['enabled'] ?? '0');
        $folder = trim((string)($conf['remote_folder'] ?? ''));
        $retention = trim((string)($conf['retention'] ?? ''));
        $newToken = trim((string)($conf['oauth_token'] ?? ''));
        $existingToken = $this->previousSecret('oauth_token');
        // Password field POSTs its displayed mask. Do not mistake it for a new OAuth token.
        $preserveToken = $newToken === '' || ($existingToken !== '' && $newToken === self::STORED_TOKEN_MASK);

        // The Python backend validates exactly the same folder constraints.
        $parts = explode('/', $folder);
        if (strlen($folder) < 1 || strlen($folder) > 160 || count($parts) > 8 ||
            $folder !== trim($folder, '/') || str_contains($folder, '\\') ||
            str_contains($folder, ':') || preg_match('/[\x00-\x1F]/', $folder)) {
            $errors[] = gettext('The remote folder path is invalid.');
        }
        foreach ($parts as $segment) {
            if ($segment === '' || $segment === '.' || $segment === '..') {
                $errors[] = gettext('The remote folder cannot contain empty, dot or parent-directory segments.');
                break;
            }
        }
        if (!ctype_digit($retention) || (int)$retention < 1 || (int)$retention > 365) {
            $errors[] = gettext('Backups to keep must be an integer from 1 to 365.');
        }
        if ($newToken === self::STORED_TOKEN_MASK && $existingToken === '') {
            $errors[] = gettext('Please enter a valid OAuth token instead of the display placeholder.');
        } elseif ($enabled === '1' && $preserveToken && $existingToken === '') {
            $errors[] = gettext('Please enter a Yandex OAuth token.');
        }
        if ($errors) {
            $this->maskLegacyPostedToken($existingToken !== '');
            return $errors;
        }

        $model = $this->model();
        $model->general->enabled->setValue($enabled);
        if (!$preserveToken) {
            $model->general->oauth_token->setValue($newToken);
        } // Retain the stored token when the mask is unchanged or the field is empty.
        $model->general->remote_folder->setValue($folder);
        $model->general->retention->setValue($retention);
        $model->serializeToConfig();
        Config::getInstance()->save();
        $this->maskLegacyPostedToken($this->previousSecret('oauth_token') !== '');
        return [];
    }

    public function isEnabled()
    {
        return (string)$this->model()->general->enabled === '1';
    }

    public function backup()
    {
        if (!$this->isEnabled()) {
            return [];
        }
        // configd executes the existing Python backend as root: no shell arguments or secrets.
        $output = trim((new Backend())->configdRun('yandexbackup backup'));
        $result = json_decode($output, true);
        if (!is_array($result) || empty($result['ok'])) {
            $reason = is_array($result) && !empty($result['message'])
                ? (string)$result['message']
                : gettext('Yandex Disk backup failed; inspect System > Log Files > Backend and console status.');
            throw new \RuntimeException($reason);
        }
        return !empty($result['file']) ? [(string)$result['file']] : [];
    }
}
