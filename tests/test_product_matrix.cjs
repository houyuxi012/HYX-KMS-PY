const assert = require('node:assert/strict');
const fs = require('node:fs');
const { buildScript } = require('../hyx_kms_py/static/js/activation.js');
const catalog = JSON.parse(fs.readFileSync(0, 'utf8'));
let count = 0;
for (const [family, groups] of Object.entries(catalog)) {
    for (const group of groups) for (const item of group.items) {
        for (const architecture of family === 'Office' ? ['x64', 'x86'] : ['x64']) {
            for (const [host, port] of [['kms.example.com', 1688], ['192.0.2.1', 1689], ['2001:db8::1', 1688]]) {
                const script = buildScript(family, item.gvlk, host, port, item.name, architecture);
                assert.ok(script.includes(item.gvlk), item.name);
                assert.equal(script.replace(/\r\n/g, '').includes('\n'), false);
                assert.ok([...script].every(c => c.charCodeAt(0) < 128));
                if (family === 'Office') {
                    const year = item.name.match(/20\d\d/)[0];
                    const version = year === '2010' ? '14' : year === '2013' ? '15' : '16';
                    assert.ok(script.includes('Office' + version + '\\OSPP.VBS'), item.name);
                    assert.ok(script.includes('/sethst:' + host));
                    assert.ok(script.includes('/setprt:' + port));
                    assert.ok(script.includes('/dstatus\r\nif errorlevel 1 goto failed'));
                    assert.equal(script.includes('if defined ProgramFiles(x86)'), architecture === 'x86');
                } else {
                    const address = host.includes(':') ? '[' + host + ']:' + port : host + ':' + port;
                    assert.ok(script.includes('/skms ' + address));
                    assert.ok(script.includes('/xpr\r\nif errorlevel 1 goto failed'));
                }
                count++;
            }
        }
    }
}
assert.throws(() => buildScript('Office', 'AAAAA-AAAAA-AAAAA-AAAAA-AAAAA', 'kms.test', 1688, 'Office 2030'));
console.log('PASS ' + count + ' edition / architecture / endpoint script combinations');
