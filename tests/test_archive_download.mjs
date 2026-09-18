import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
let extension;
const elements = [];
globalThis.document = { createElement: () => {
    const item = { style: {}, append() {}, removeAttribute(name) { delete this[name]; } };
    elements.push(item);
    return item;
} };
globalThis.__archiveTest = {
    app: { registerExtension(value) { extension = value; } },
    api: { apiURL: path => '/comfy' + path },
    ComfyWidgets: { STRING: () => ({ widget: { inputEl: {} } }) },
};
const code = (await readFile(new URL('../web/archive_download.js', import.meta.url), 'utf8')).replace(/^import .*;\r?\n/gm, '');
await import('data:text/javascript;base64,' + Buffer.from('const {app,api,ComfyWidgets}=globalThis.__archiveTest;\n' + code).toString('base64'));
for (const [type, key, filename] of [
    ['ServerPathArchive', 'server_path_archive', 'server_path_' + 'a'.repeat(32) + '.zip'],
    ['CustomNodesArchive', 'custom_nodes_archive', 'custom_nodes_123_test.zip'],
]) {
    const node = { comfyClass: type, addDOMWidget() {}, setSize() {}, setDirtyCanvas() {} };
    extension.nodeCreated(node);
    const link = elements.at(-1);
    node.onExecuted({ text: ['success'], [key]: [filename] });
    assert.equal(link.href, '/comfy/view?filename=' + filename + '&type=output');
    node.onExecuted({ text: ['not found'], [key]: [''] });
    assert.equal(link.href, undefined);
    node.onExecuted({ text: [], [key]: ['../private.zip'] });
    assert.equal(link.href, undefined);
}
console.log('PASS: path archive and existing archive download links, failure clears old URL, invalid filename rejected');
