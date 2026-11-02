<?php
/** Offline smoke tests for PHP 8.x. Does not require OPNsense or network. */
namespace OPNsense\Backup {
    interface IBackupProvider {
        public function getConfigurationFields();
        public function setConfiguration($conf);
        public function getName();
        public function backup();
        public function isEnabled();
    }
}
namespace OPNsense\Core {
    class Config {
        public static ?self $instance = null;
        public object $obj;
        public int $saved = 0;
        private function __construct() {
            $this->obj = (object)['OPNsense'=>(object)['yandexbackup'=>(object)['general'=>(object)[
                'enabled'=>'0','oauth_token'=>'old-token','remote_folder'=>'OldFolder',
                'retention'=>'30','encrypt'=>'1','encrypt_password'=>'a-long-original-password',
            ]]]];
        }
        public static function getInstance(): self {return self::$instance ??= new self();}
        public function object(): object {return $this->obj;}
        public function save(): void {$this->saved++;}
    }
    class Backend {
        public static string $result = '{"ok":true,"file":"new.xml"}';
        public function configdRun($command) {
            if ($command !== 'yandexbackup backup') throw new \RuntimeException('Bad command');
            return self::$result;
        }
    }
}
namespace OPNsense\YandexBackup {
    use OPNsense\Core\Config;
    class Field {
        public string $value;
        public bool $updateOnly;
        function __construct(string $value='', bool $updateOnly=false) { $this->value=$value; $this->updateOnly=$updateOnly; }
        public function __toString(): string {return $this->updateOnly ? '' : $this->value;}
        public function setValue(string $v): void { if (!$this->updateOnly || $v !== '') $this->value=$v; }
    }
    class General {
        public object $general;
        public function __construct() {
            $conf=Config::getInstance()->object()->OPNsense->yandexbackup->general;
            $this->general = new \stdClass();
            foreach (get_object_vars($conf) as $k=>$v) {
                $this->general->{$k} = new Field($v, in_array($k, ['oauth_token', 'encrypt_password'], true));
            }
        }
        public function serializeToConfig(): void {
            $conf=Config::getInstance()->object()->OPNsense->yandexbackup->general;
            foreach (get_object_vars($this->general) as $k=>$v) { $conf->{$k} = $v->value; }
        }
    }
}
namespace {
    require __DIR__.'/../src/opnsense/mvc/app/library/OPNsense/Backup/YandexDisk.php';
    function check($c, $message) {if (!$c) throw new \RuntimeException("FAIL: ".$message);}
    $p=new OPNsense\Backup\YandexDisk();
    $f=$p->getConfigurationFields();
    check(count($f)===4, 'four fields');
    check($f[1]['value']==='********', 'saved token is represented by fixed mask');
    check($f[1]['type']==='password', 'masked field is a password input');
    check($f[1]['value']!=='old-token', 'actual token never disclosed by provider');
    check($p->getName()==='Yandex Disk', 'clean provider name');
    check(count(array_filter($f, fn($x) => in_array($x['name'], ['encrypt','encrypt_password'])))===0, 'no encrypt fields');
    check(!$p->isEnabled(), 'initial disabled');
    $errors=$p->setConfiguration(['enabled'=>'on','oauth_token'=>'','remote_folder'=>'OPNsense-Backups/Home',
        'retention'=>'30']);
    check($errors === [],'new settings accepted with unchanged secrets '.json_encode($errors));
    $conf=OPNsense\Core\Config::getInstance()->object()->OPNsense->yandexbackup->general;
    check($conf->oauth_token==='old-token', 'old OAuth token preserved');
    $errors=$p->setConfiguration(['enabled'=>'on','oauth_token'=>'********',
        'remote_folder'=>'OPNsense-Backups/Home','retention'=>'30']);
    check($errors === [], 're-save with unchanged masked token succeeds');
    check($conf->oauth_token==='old-token', 'masked token never replaces original');
    $GLOBALS['pconfig']=['YandexDisk_oauth_token'=>'new-valid-looking-oauth-token'];
    $errors=$p->setConfiguration(['enabled'=>'on','oauth_token'=>'new-valid-looking-oauth-token',
        'remote_folder'=>'OPNsense-Backups/Home','retention'=>'30']);
    check($errors === [], 'changing token succeeds');
    check($GLOBALS['pconfig']['YandexDisk_oauth_token']==='********',
        'new token not echoed back in native Setup/Test HTML');
    check($conf->oauth_token==='new-valid-looking-oauth-token', 'replacement token persisted');
    check($p->getConfigurationFields()[1]['value']==='********', 'token stays masked after replacement');
    $errors=$p->setConfiguration(['enabled'=>'on','oauth_token'=>'',
        'remote_folder'=>'OPNsense-Backups/Home','retention'=>'30']);
    check($errors === [] && $conf->oauth_token==='new-valid-looking-oauth-token',
        'blank token preserves replacement');
    $GLOBALS['pconfig']=['YandexDisk_oauth_token'=>'unsaved-sensitive-token'];
    $errors=$p->setConfiguration(['enabled'=>'on','oauth_token'=>'unsaved-sensitive-token',
        'remote_folder'=>'../bad','retention'=>'30']);
    check(count($errors)>0 && $GLOBALS['pconfig']['YandexDisk_oauth_token']==='********',
        'unsaved token redacted on validation errors');
    check($conf->oauth_token==='new-valid-looking-oauth-token', 'invalid update did not alter saved token');
    $conf->oauth_token='';
    check($p->getConfigurationFields()[1]['value']==='', 'new installation has empty token field');
    $errors=$p->setConfiguration(['enabled'=>'on','oauth_token'=>'********',
        'remote_folder'=>'OPNsense-Backups/Home','retention'=>'30']);
    check(count($errors)>0, 'mask cannot be saved without an existing token');
    $conf->oauth_token='new-valid-looking-oauth-token';
    check($conf->encrypt_password==='a-long-original-password', 'legacy password not deleted');
    check($p->isEnabled() && count($p->backup())===1, 'backup returns file');
    $errors=$p->setConfiguration(['enabled'=>'on', 'remote_folder'=>'../../etc', 'retention'=>'30']);
    check(count($errors)>0,'folder traversal rejected');
    check($conf->remote_folder==='OPNsense-Backups/Home','invalid config not persisted');
    $errors=$p->setConfiguration(['enabled'=>'on','remote_folder'=>'Backup','retention'=>'366']);
    check(count($errors)>0,'retention validated');
    OPNsense\Core\Backend::$result='{"ok":false,"message":"Yandex.Disk API returned HTTP 401"}';
    try { $p->backup(); throw new \RuntimeException('failed backup not detected'); }
    catch (\RuntimeException $e) { check(str_contains($e->getMessage(), '401'), 'failure message propagated'); }
    echo "PHP native provider smoke tests OK\n";
}
