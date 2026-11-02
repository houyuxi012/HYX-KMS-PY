(function (root) {
    'use strict';
    const messages = typeof document === 'undefined' ? {} : JSON.parse(document.getElementById('ui-messages').textContent);
    function t(message) { return messages[message] || message; }
    function endpoint(host, port) {
        host = host.trim();
        const number = Number(port);
        if (!/^\d+$/.test(String(port)) || !Number.isInteger(number) || number < 1 || number > 65535) {
            throw new Error(t('端口必须为 1 到 65535 的整数。'));
        }
        // Only literal addresses or DNS names can enter the downloaded CMD file.
        if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1);
        if (host.includes(':')) {
            if (!/^[0-9a-f:]+$/i.test(host)) throw new Error(t('IPv6 地址格式不正确。'));
            try { new URL('http://[' + host + ']/'); }
            catch (_) { throw new Error(t('IPv6 地址格式不正确。')); }
            return { host: host, windows: '[' + host + ']:' + number, port: number };
        }
        if (host.length > 253 || !host.split('.').every(function (part) {
            return /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(part);
        })) throw new Error(t('请输入有效的主机名或 IP，不要包含协议、路径、空格或命令符号。'));
        if (/^[\d.]+$/.test(host) && (host.split('.').length !== 4 || host.split('.').some(function (p) { return Number(p) > 255; }))) {
            throw new Error(t('IPv4 地址格式不正确。'));
        }
        return { host: host, windows: host + ':' + number, port: number };
    }
    function buildScript(family, key, host, port, productName, architecture = 'x64') {
        if (!/^[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}$/.test(key)) throw new Error(t('请选择有效的产品版本。'));
        if (!['Windows', 'Windows Server', 'Office'].includes(family)) throw new Error(t('未知产品类型。'));
        const address = endpoint(host, port);
        const lines = ['@echo off', 'setlocal'];
        if (family === 'Windows' || family === 'Windows Server') {
            lines.push('cscript //nologo "%SystemRoot%\\System32\\slmgr.vbs" /ipk ' + key,
                'if errorlevel 1 goto failed',
                'cscript //nologo "%SystemRoot%\\System32\\slmgr.vbs" /skms ' + address.windows,
                'if errorlevel 1 goto failed',
                'cscript //nologo "%SystemRoot%\\System32\\slmgr.vbs" /ato',
                'if errorlevel 1 goto failed',
                'cscript //nologo "%SystemRoot%\\System32\\slmgr.vbs" /xpr');
        } else {
            if (!['x64', 'x86'].includes(architecture)) throw new Error(t('请选择 64 位或 32 位 Office。'));
            const year = (productName.match(/20(?:10|13|16|19|21|24)/) || [])[0];
            if (!year) throw new Error(t('请选择有效的产品版本。'));
            const version = year === '2010' ? '14' : year === '2013' ? '15' : '16';
            lines.push('rem Office architecture: ' + architecture, 'set "OFFICE_ROOT=%ProgramFiles%"');
            if (architecture === 'x64') {
                lines.push('if defined ProgramW6432 set "OFFICE_ROOT=%ProgramW6432%"');
            } else {
                lines.push('if defined ProgramFiles(x86) set "OFFICE_ROOT=%ProgramFiles(x86)%"');
            }
            lines.push('set "OSPP="');
            ['root\\', ''].forEach(function (subdir) {
                const path = '%OFFICE_ROOT%\\Microsoft Office\\' + subdir + 'Office' + version + '\\OSPP.VBS';
                lines.push('if not defined OSPP if exist "' + path + '" set "OSPP=' + path + '"');
            });
            lines.push('if not defined OSPP (', '  echo Office licensing script not found. Check the selected architecture and installed volume edition.', '  goto failed', ')',
                'cscript //nologo "%OSPP%" /inpkey:' + key, 'if errorlevel 1 goto failed',
                'cscript //nologo "%OSPP%" /sethst:' + address.host, 'if errorlevel 1 goto failed',
                'cscript //nologo "%OSPP%" /setprt:' + address.port, 'if errorlevel 1 goto failed',
                'cscript //nologo "%OSPP%" /act', 'if errorlevel 1 goto failed',
                'cscript //nologo "%OSPP%" /dstatus');
        }
        lines.push('if errorlevel 1 goto failed', 'pause', 'exit /b 0', ':failed', 'echo Activation failed. Run as administrator and check the product and KMS server.', 'pause', 'exit /b 1');
        return lines.join('\r\n') + '\r\n';
    }
    if (typeof module !== 'undefined') module.exports = { endpoint: endpoint, buildScript: buildScript };
    if (typeof document === 'undefined') return;
    const products = JSON.parse(document.getElementById('products-data').textContent);
    const family = document.getElementById('family-select');
    const architectureField = document.getElementById('office-architecture');
    const architectureOptions = document.querySelectorAll('input[name="office-architecture"]');
    const select = document.getElementById('product-select');
    const host = document.getElementById('server-input');
    const port = document.getElementById('port-input');
    const output = document.getElementById('script-output');
    const keyInput = document.getElementById('gvlk-input');
    const error = document.getElementById('activation-error');
    const copy = document.getElementById('copy-button');
    const download = document.getElementById('download-button');
    const picker = document.getElementById('edition-picker');
    const trigger = document.getElementById('edition-trigger');
    const menu = document.getElementById('edition-menu');
    const editionValue = document.getElementById('edition-value');
    function closeEditions(restoreFocus) {
        menu.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        if (restoreFocus) trigger.focus();
    }
    function openEditions() {
        menu.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        const selected = menu.querySelector('[aria-selected="true"]');
        if (selected) selected.focus({ preventScroll: true });
        if (selected) selected.scrollIntoView({ block: 'nearest' });
    }
    function syncEdition() {
        const selected = select.options[select.selectedIndex];
        editionValue.textContent = selected ? selected.textContent : t('暂无可选版本');
        trigger.disabled = !selected;
        menu.querySelectorAll('[role="option"]').forEach(function (option) {
            option.setAttribute('aria-selected', String(option.dataset.value === select.value));
        });
    }
    function renderEditionGroups() {
        closeEditions(false);
        menu.replaceChildren();
        Array.from(select.children).forEach(function (group, index) {
            const section = document.createElement('div');
            section.setAttribute('role', 'group');
            const heading = document.createElement('div');
            heading.id = 'edition-group-' + index;
            heading.className = 'edition-group-label';
            heading.textContent = group.label;
            section.setAttribute('aria-labelledby', heading.id);
            section.appendChild(heading);
            Array.from(group.children).forEach(function (option) {
                const button = document.createElement('button');
                button.type = 'button';
                button.tabIndex = -1;
                button.setAttribute('role', 'option');
                button.dataset.value = option.value;
                button.textContent = option.textContent;
                button.addEventListener('click', function () {
                    select.value = option.value;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    closeEditions(true);
                });
                section.appendChild(button);
            });
            menu.appendChild(section);
        });
        syncEdition();
    }
    trigger.addEventListener('click', function () {
        if (menu.hidden) openEditions(); else closeEditions(false);
    });
    trigger.addEventListener('keydown', function (event) {
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            openEditions();
            const options = menu.querySelectorAll('[role="option"]');
            if (event.key === 'Home' && options.length) options[0].focus();
            if (event.key === 'End' && options.length) options[options.length - 1].focus();
        }
    });
    menu.addEventListener('keydown', function (event) {
        const options = Array.from(menu.querySelectorAll('[role="option"]'));
        const index = options.indexOf(document.activeElement);
        if (event.key === 'Escape') { event.preventDefault(); closeEditions(true); }
        else if (event.key === 'Tab') closeEditions(false);
        else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            let next = index;
            if (event.key === 'Home') next = 0;
            else if (event.key === 'End') next = options.length - 1;
            else next = Math.max(0, Math.min(options.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
            if (options[next]) options[next].focus();
        }
    });
    document.addEventListener('click', function (event) {
        if (!picker.contains(event.target)) closeEditions(false);
    });
    picker.classList.add('edition-picker');
    select.hidden = true;
    trigger.hidden = false;
    document.getElementById('product-label').htmlFor = trigger.id;

    host.value = host.value || location.hostname.replace(/^\[|\]$/g, '');
    function update() {
        if (port.value !== '1688') document.getElementById('connection-options').open = true;
        error.classList.remove('is-success');
        const item = select.options[select.selectedIndex];
        keyInput.value = item ? item.dataset.key : '';
        syncEdition();
        try {
            const architecture = document.querySelector('input[name="office-architecture"]:checked').value;
            output.value = buildScript(family.value, keyInput.value, host.value, port.value, item ? item.textContent : '', architecture);
            error.textContent = '';
            host.removeAttribute('aria-invalid');
            port.removeAttribute('aria-invalid');
            copy.disabled = download.disabled = false;
        } catch (exc) {
            output.value = '';
            error.textContent = exc.message;
            host.removeAttribute('aria-invalid');
            port.removeAttribute('aria-invalid');
            (exc.message === t('端口必须为 1 到 65535 的整数。') ? port : host).setAttribute('aria-invalid', 'true');
            copy.disabled = download.disabled = true;
        }
    }
    function populate() {
        select.replaceChildren();
        (products[family.value] || []).forEach(function (group) {
            const container = document.createElement('optgroup');
            container.label = group.group;
            group.items.forEach(function (item) {
                const option = document.createElement('option');
                option.textContent = item.name;
                option.dataset.key = item.gvlk;
                option.value = item.id + ':' + item.name;
                container.appendChild(option);
            });
            select.appendChild(container);
        });
        const defaults = { Windows: 'Windows 11 Pro', 'Windows Server': 'Windows Server 2025 Standard', Office: 'Office LTSC Professional Plus 2024' };
        const preferred = Array.from(select.options).find(function (option) { return option.textContent === defaults[family.value]; });
        if (preferred) select.value = preferred.value;
        renderEditionGroups();
        document.getElementById('windows-catalog-note').hidden = family.value !== 'Windows';
        architectureField.hidden = family.value !== 'Office';
        update();
    }
    family.addEventListener('change', populate);
    select.addEventListener('change', update);
    architectureOptions.forEach(function (option) { option.addEventListener('change', update); });
    host.addEventListener('input', update);
    port.addEventListener('input', update);
    copy.addEventListener('click', async function () {
        try {
            if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(output.value);
            else { output.select(); if (!document.execCommand('copy')) throw new Error('copy failed'); }
            error.textContent = t('脚本已复制。');
            error.classList.add('is-success');
        } catch (_) { output.focus(); output.select(); error.classList.remove('is-success'); error.textContent = t('自动复制失败，请按 Ctrl+C（Mac 为 Command+C）复制选中脚本。'); }
    });
    download.addEventListener('click', function () {
        const url = URL.createObjectURL(new Blob([output.value], { type: 'application/octet-stream' }));
        const link = document.createElement('a');
        link.href = url; link.download = 'kms.bat'; document.body.appendChild(link); link.click(); link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
    populate();
    // Preserve the current form only across an explicit language switch in this tab.
    const stateKey = 'kms-language-form';
    try {
        const saved = JSON.parse(sessionStorage.getItem(stateKey) || 'null');
        sessionStorage.removeItem(stateKey);
        if (saved && ['Windows', 'Windows Server', 'Office'].includes(saved.family)) {
            family.value = saved.family;
            populate();
            if (Array.from(select.options).some(option => option.value === saved.edition)) select.value = saved.edition;
            const architecture = Array.from(architectureOptions).find(option => option.value === saved.architecture);
            if (architecture) architecture.checked = true;
            if (typeof saved.host === 'string') host.value = saved.host;
            if (typeof saved.port === 'string') port.value = saved.port;
            update();
        }
    } catch (_) { /* Storage may be disabled by the browser. */ }
    document.querySelector('.language-switch').addEventListener('submit', function () {
        try {
            sessionStorage.setItem(stateKey, JSON.stringify({ family: family.value, edition: select.value,
                architecture: document.querySelector('input[name="office-architecture"]:checked').value,
                host: host.value, port: port.value }));
        } catch (_) { /* Language selection still works without browser storage. */ }
    });
})(typeof globalThis !== 'undefined' ? globalThis : this);
