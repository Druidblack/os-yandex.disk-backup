<script type="text/javascript">
$(document).ready(function () {
    mapDataToFormUI({'frm_YandexBackup': '/api/yandexbackup/settings/get'}).done(function () {
        updateStatus();
    });

    function displayResult(data) {
        var el = $('#yd-result');
        el.empty();
        el.removeClass('alert-success alert-danger');
        el.addClass(data && data.ok ? 'alert-success' : 'alert-danger');
        el.text(data && data.message ? data.message : 'Unexpected response from backend');
    }

    function runAction(action, button) {
        var btn = $(button);
        btn.prop('disabled', true);
        $('#yd-result').text('Working...').removeClass('alert-success alert-danger');
        ajaxCall('/api/yandexbackup/service/' + action, {}, function (data) {
            displayResult(data);
            btn.prop('disabled', false);
            updateStatus();
            if (action === 'list') {
                var tbody = $('#yd-files');
                tbody.empty();
                if (data && data.ok && Array.isArray(data.files)) {
                    data.files.forEach(function (entry) {
                        var tr = $('<tr>');
                        $('<td>').text(entry.name || '').appendTo(tr);
                        $('<td>').text(entry.size || 0).appendTo(tr);
                        $('<td>').text(entry.created || '').appendTo(tr);
                        tbody.append(tr);
                    });
                    $('#yd-total').text('Showing ' + data.files.length + ' of ' + data.total + ' backups for this firewall');
                }
            }
        });
    }

    function updateStatus() {
        ajaxCall('/api/yandexbackup/service/status', {}, function (data) {
            if (!(data && data.ok)) { return; }
            $('#yd-summary').text('Enabled: ' + (data.enabled ? 'yes' : 'no') +
                ' | Token: ' + (data.token_configured ? 'configured' : 'missing'));
            // MVC UpdateOnlyTextField intentionally returns an empty value. Show status
            // through a placeholder; never inject the actual token or a submitted mask.
            $('#frm_YandexBackup input[type="password"]').attr({
                'placeholder': data.token_configured ? '••••••••' : '',
                'autocomplete': 'new-password'
            });
            var tbody = $('#yd-history');
            tbody.empty();
            (data.history || []).forEach(function (entry) {
                var tr = $('<tr>');
                $('<td>').text(entry.time || '').appendTo(tr);
                $('<td>').text(entry.action || '').appendTo(tr);
                $('<td>').text(entry.ok ? 'OK' : 'ERROR').appendTo(tr);
                $('<td>').text(entry.message || '').appendTo(tr);
                $('<td>').text(entry.file || '').appendTo(tr);
                tbody.append(tr);
            });
        });
    }

    $('#yd-save').click(function () {
        saveFormToEndpoint('/api/yandexbackup/settings/set', 'frm_YandexBackup', function () {
            $('#yd-result').removeClass('alert-danger').addClass('alert-success').text('Settings saved');
            $('#frm_YandexBackup input[type="password"]').val('');
            updateStatus();
        });
    });
    $('#yd-test').click(function () { runAction('test', this); });
    $('#yd-backup').click(function () { runAction('backup', this); });
    $('#yd-list').click(function () { runAction('list', this); });
    $('#yd-refresh').click(function () { updateStatus(); });
});
</script>
<div class="content-box">
    <div class="row">
        <div class="col-md-12">
            <h2>Yandex Disk Backup</h2>
            <p>OPNsense configuration backups on Yandex.Disk.</p>
            {{ partial('layout_partials/base_form', ['fields': generalForm, 'id': 'frm_YandexBackup']) }}
            <div class="form-group">
                <button class="btn btn-primary" type="button" id="yd-save">Save settings</button>
                <button class="btn btn-default" type="button" id="yd-test">Test connection</button>
                <button class="btn btn-success" type="button" id="yd-backup">Backup now</button>
                <button class="btn btn-default" type="button" id="yd-list">List backups</button>
                <button class="btn btn-default" type="button" id="yd-refresh">Refresh status</button>
            </div>
            <div id="yd-result" class="alert" role="status"></div>
            <p id="yd-summary"></p>
            <h3>Backups on Yandex.Disk</h3>
            <p id="yd-total"></p>
            <div class="table-responsive"><table class="table table-striped table-condensed">
                <thead><tr><th>Filename</th><th>Bytes</th><th>Created (UTC)</th></tr></thead>
                <tbody id="yd-files"></tbody>
            </table></div>
            <h3>Operation history</h3>
            <div class="table-responsive"><table class="table table-striped table-condensed">
                <thead><tr><th>UTC</th><th>Action</th><th>Result</th><th>Message</th><th>File</th></tr></thead>
                <tbody id="yd-history"></tbody>
            </table></div>
            <p>For automatic backups, use <strong>System &rarr; Settings &rarr; Cron</strong> and select the command <strong>Yandex Disk Backup</strong>. Download an XML backup from your Yandex.Disk and import it using System &rarr; Configuration &rarr; Backups &rarr; Restore. These files contain sensitive configuration data; restrict access to your Disk account.</p>
        </div>
    </div>
</div>
