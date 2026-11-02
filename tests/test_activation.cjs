const assert = require('node:assert/strict');
const { endpoint, buildScript } = require('../hyx_kms_py/static/js/activation.js');
const key = Array(5).fill('AAAAA').join('-');
for (const host of ['', 'a&calc', 'a\nb', 'a%PATH%', 'a"', 'http://kms.test', '-a', 'a..b', '999.1.1.1', 'x/y']) {
    assert.throws(() => endpoint(host, 1688), host);
}
for (const port of ['', 0, 65536, '1688&calc', '1.5']) assert.throws(() => endpoint('kms.test', port));
assert.equal(endpoint('[2001:db8::1]', 1688).windows, '[2001:db8::1]:1688');
assert.throws(() => endpoint('::::', 1688));
assert.equal(endpoint('192.168.1.10', 1689).windows, '192.168.1.10:1689');
const windows = buildScript('Windows', key, 'kms.test', 1688, 'Windows 11 Professional');
assert.ok(windows.includes('/skms kms.test:1688'));
assert.ok(windows.includes('slmgr.vbs'));
assert.ok(!windows.includes('OSPP'));
const server = buildScript('Windows Server', key, 'kms.test', 1688, 'Windows Server 2025 Standard');
assert.equal(server, windows);
assert.throws(() => buildScript('Unknown', key, 'kms.test', 1688, 'Unknown'));
for (const [year, version] of [[2010, 14], [2013, 15], [2016, 16], [2019, 16], [2021, 16], [2024, 16]]) {
    const office = buildScript('Office', key, 'kms.test', 1689, 'Office Professional Plus ' + year);
    assert.ok(office.includes('Office' + version + '\\OSPP.VBS'));
    assert.ok(office.includes('/sethst:kms.test'));
    assert.ok(office.includes('/setprt:1689'));
    assert.ok(!office.includes('slmgr'));
    assert.ok(office.includes('if not defined OSPP'));
    for (const architecture of ['x64', 'x86']) {
        const script = buildScript('Office', key, 'kms.test', 1689, 'Office Professional Plus ' + year, architecture);
        assert.ok(script.includes('set "OFFICE_ROOT=%ProgramFiles%"'));
        assert.ok(script.includes('Office' + version + '\\OSPP.VBS'));
        assert.ok(script.includes('root\\Office' + version + '\\OSPP.VBS'));
        assert.ok(script.includes('/inpkey:' + key));
        assert.ok(script.includes('/act'));
        assert.equal(script.includes('%ProgramW6432%'), architecture === 'x64');
        assert.equal(script.includes('%ProgramFiles(x86)%'), architecture === 'x86');
    }
}
assert.throws(() => buildScript('Office', key, 'kms.test', 1688, 'Office 2024', 'x64&calc'));
assert.equal(buildScript('Windows', key, 'kms.test', 1688, 'Windows 11 Pro', 'x86'), windows);
assert.throws(() => buildScript('Office', 'bad&key', 'kms.test', 1688, 'Office 2024'));
console.log('PASS: host/port validation, injection rejection, IPv6, Windows and Office 2010–2024 commands');
