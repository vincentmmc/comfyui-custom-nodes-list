import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const source = await readFile(new URL("../web/restore_plan.js", import.meta.url), "utf8");
const { prepareRestoration, applyRestoration } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

class Node {
    constructor(type, inputs = [], widgets = []) {
        this.type = this.title = type;
        this.inputs = inputs.map(name => ({ name, type: "*", link: null }));
        this.widgets = widgets.map(name => ({ name, value: 0 }));
        this.outputs = [{ name: "out", type: "*", links: [] }];
        this.pos = [0, 0]; this.size = [200, 100];
    }
    addInput(name, type) { this.inputs.push({ name, type, link: null }); }
    setSize(size) { this.size = size; }
    connect(origin_slot, target, target_slot) {
        const graph = this.graph;
        const old = target.inputs[target_slot].link;
        if (old != null) graph.unlink(old);
        const id = ++graph.lastLink;
        graph.links[id] = { id, origin_id: this.id, origin_slot, target_id: target.id, target_slot };
        this.outputs[origin_slot].links.push(id);
        target.inputs[target_slot].link = id;
        return graph.links[id];
    }
}
class Graph {
    nodes = []; links = {}; lastLink = 0; nextId = 0;
    add(node) { node.id = ++this.nextId; node.graph = this; this.nodes.push(node); }
    getNodeById(id) { return this.nodes.find(n => n.id === id); }
    unlink(id) {
        const link = this.links[id];
        const out = this.getNodeById(link.origin_id).outputs[link.origin_slot];
        out.links = out.links.filter(i => i !== id);
        this.getNodeById(link.target_id).inputs[link.target_slot].link = null;
        delete this.links[id];
    }
    remove(node) {
        for (const link of Object.values(this.links)) {
            if (link.origin_id === node.id || link.target_id === node.id) this.unlink(link.id);
        }
        this.nodes = this.nodes.filter(n => n !== node);
    }
}
const graph = new Graph();
const upstream = new Node("up");
const group = new Node("LamGroupNode", ["outside"]);
const sink1 = new Node("sink", ["in"]), sink2 = new Node("sink", ["in"]);
for (const n of [upstream, group, sink1, sink2]) graph.add(n);
upstream.connect(0, group, 0); group.connect(0, sink1, 0); group.connect(0, sink2, 0);
const plan = {
    nodes: [
        { id: "1", class_type: "A", inputs: { input: { kind: "external", name: "outside" }, seed: { kind: "value", value: 123 } } },
        { id: "2", class_type: "B", inputs: { dynamic: { kind: "link", node: "1", slot: 0 } } },
    ],
    outputs: { 0: { kind: "link", node: "2", slot: 0 } },
};
const lite = { registered_node_types: { A: true, B: true }, createNode: type => new Node(type, [], type === "A" ? ["input", "seed"] : []) };
const converter = (node, widget) => node.addInput(widget.name, "*");
const before = graph.nodes.length;
assert.throws(() => prepareRestoration(graph, group, plan, { ...lite, registered_node_types: {} }, converter), /先安装/);
assert.equal(graph.nodes.length, before);
const prepared = prepareRestoration(graph, group, plan, lite, converter);
assert.equal(graph.nodes.length, before); // Preparation must not edit the live graph.
assert.equal(prepared.nodes.get("1").node.widgets.find(w => w.name === "seed").value, 123);
assert.equal(applyRestoration(graph, group, prepared), 2);
assert.ok(!graph.nodes.includes(group));
assert.equal(Object.keys(graph.links).length, 4);
const restoredB = prepared.nodes.get("2").node;
for (const sink of [sink1, sink2]) assert.equal(graph.links[sink.inputs[0].link].origin_id, restoredB.id);
assert.equal(graph.links[prepared.nodes.get("1").node.inputs[0].link].origin_id, upstream.id);

// A connection refused by an extension must fail loudly, so the UI can roll back.
const graph2 = new Graph(), group2 = new Node("LamGroupNode", ["outside"]), up2 = new Node("up");
graph2.add(up2); graph2.add(group2); up2.connect(0, group2, 0);
const rejected = prepareRestoration(graph2, group2, plan, lite, converter);
up2.connect = () => null;
assert.throws(() => applyRestoration(graph2, group2, rejected), /无法连接/);
assert.ok(graph2.nodes.includes(group2));
console.log("PASS: missing nodes, preflight isolation, widget conversion, dynamic inputs, parameters, external input, output fanout, refused connection");

// Exercise the actual menu callback and rollback path with a failed connection.
const graph3 = new Graph(), group3 = new Node("LamGroupNode", ["outside"]), up3 = new Node("up");
graph3.add(up3); graph3.add(group3); up3.connect(0, group3, 0);
group3.properties = { hiddenJson: "test cipher" };
const backup = { test: "original workflow" };
graph3.serialize = () => backup;
up3.connect = () => null;
let registered, restoredSnapshot, downloaded = false;
const alerts = [];
globalThis.__restoreEnv = {
    app: {
        graph: graph3,
        registerExtension: ext => { registered = ext; },
        loadGraphData: async data => { restoredSnapshot = data; },
        canvas: { setDirty() {} },
    },
    api: { fetchApi: async () => ({ ok: true, status: 200, json: async () => ({ success: true, ...plan }) }) },
    prepareRestoration, applyRestoration,
};
// Provide sockets directly: this simulates current ComfyUI without the legacy converter.
globalThis.LiteGraph = { ...lite, createNode: type => new Node(type, type === "A" ? ["input"] : [], type === "A" ? ["seed"] : []) };
globalThis.alert = value => alerts.push(value);
globalThis.document = { createElement: () => ({ click() { downloaded = true; } }) };
const realTimeout = globalThis.setTimeout, realError = console.error;
globalThis.setTimeout = callback => { callback(); return 0; };
console.error = () => {};
try {
    const uiSource = (await readFile(new URL("../web/restore_group.js", import.meta.url), "utf8"))
        .replace(/^import .*;\r?\n/gm, "");
    const injected = "const { app, api, prepareRestoration, applyRestoration } = globalThis.__restoreEnv;\n" + uiSource;
    await import(`data:text/javascript;base64,${Buffer.from(injected).toString("base64")}`);
    registered.nodeCreated(group3);
    const options = [];
    group3.getExtraMenuOptions(null, options);
    assert.match(options[0].content, /还原成普通节点/);
    await options[0].callback();
    assert.ok(downloaded);
    assert.deepEqual(restoredSnapshot, backup);
    assert.match(alerts[0], /已恢复还原前/);
} finally {
    globalThis.setTimeout = realTimeout;
    console.error = realError;
}
console.log("PASS: right-click menu, backup download, connection failure invokes snapshot rollback");
