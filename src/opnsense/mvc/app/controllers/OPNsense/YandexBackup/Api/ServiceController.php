<?php

namespace OPNsense\YandexBackup\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;

class ServiceController extends ApiControllerBase
{
    private function invokeBackend($action)
    {
        if (!$this->request->isPost()) {
            return ['ok' => false, 'message' => 'Only POST requests are supported'];
        }
        // Action is a compile-time constant from the methods below; no user input in commands.
        $output = trim((new Backend())->configdRun('yandexbackup ' . $action));
        $data = json_decode($output, true);
        if (is_array($data) && isset($data['ok'])) {
            return $data;
        }
        return ['ok' => false, 'message' => 'Backend failed. Check configd and console logs.'];
    }

    public function statusAction()
    {
        return $this->invokeBackend('status');
    }

    public function testAction()
    {
        return $this->invokeBackend('test');
    }

    public function backupAction()
    {
        return $this->invokeBackend('backup');
    }

    public function listAction()
    {
        return $this->invokeBackend('list');
    }
}
