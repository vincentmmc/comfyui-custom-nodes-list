// Pure graph operations kept separate from the ComfyUI extension for testing.
export function prepareRestoration(graph, group, plan, liteGraph, convertToInput) {
    if (!Array.isArray(plan.nodes) || !plan.nodes.length || !plan.outputs) {
        throw new Error("服务器返回了空的还原计划。");
    }
    const missing = [...new Set(plan.nodes.map(n => n.class_type))]
        .filter(type => !liteGraph.registered_node_types[type]);
    if (missing.length) throw new Error(`需要先安装这些节点：\n${missing.join("\n")}`);
    const nodes = new Map();
    for (const spec of plan.nodes) {
        const node = liteGraph.createNode(spec.class_type);
        if (!node) throw new Error(`无法创建节点：${spec.class_type}`);
        node.mode = group.mode ?? 0;
        if (spec.title) node.title = spec.title;
        for (const [name, input] of Object.entries(spec.inputs)) {
            if (input.kind !== "value") continue;
            const widget = node.widgets?.find(w => w.name === name);
            if (!widget) throw new Error(`${spec.class_type} 缺少参数 ${name}，可能是节点版本不一致。`);
            widget.value = structuredClone(input.value);
        }
        // A hidden group's seed is a fixed value unless supplied through a link.
        for (const widget of node.widgets ?? []) {
            if (widget.name === "control_after_generate" && widget.options?.values?.includes("fixed")) widget.value = "fixed";
        }
        nodes.set(spec.id, { node, spec });
    }

    function endpoint(value) {
        if (value.kind === "link") {
            const source = nodes.get(value.node)?.node;
            if (!source?.outputs?.[value.slot]) throw new Error("内部输出端口不存在，可能是节点版本不一致。");
            return { node: source, slot: value.slot };
        }
        if (value.kind === "missing") return null;
        if (value.kind !== "external") throw new Error("输出连接数据无效。");
        const input = group.inputs?.find(i => i.name === value.name);
        if (!input) throw new Error(`隐藏组缺少输入端口 ${value.name}。`);
        if (input.link == null) return null;
        const link = graph.links[input.link];
        const source = link && graph.getNodeById(link.origin_id);
        if (!source?.outputs?.[link.origin_slot] || source === group) throw new Error("隐藏组外部输入连接无效。");
        return { node: source, slot: link.origin_slot };
    }

    const connections = [];
    for (const { node, spec } of nodes.values()) {
        for (const [name, value] of Object.entries(spec.inputs)) {
            if (value.kind === "value") continue;
            const source = endpoint(value);
            let input = node.inputs?.find(i => i.name === name);
            if (!input) {
                const widget = node.widgets?.find(w => w.name === name);
                if (widget) {
                    if (!convertToInput) throw new Error(`当前前端无法转换 ${spec.class_type}.${name} 为输入端口。`);
                    convertToInput(node, widget);
                    input = node.inputs?.find(i => i.name === name);
                    if (!input) throw new Error(`无法转换输入端口 ${spec.class_type}.${name}。`);
                } else {
                    // Variadic nodes (e.g. rgthree switches) may grow their inputs.
                    const type = source?.node.outputs[source.slot].type ?? "*";
                    node.addInput(name, type);
                }
            }
            if (source) connections.push({ source, target: node, inputName: name });
        }
    }
    for (let index = 0; index < (group.outputs?.length ?? 0); index++) {
        const links = group.outputs[index].links ?? [];
        if (!links.length) continue;
        const value = plan.outputs[index];
        if (!value) throw new Error(`隐藏组缺少输出 ${index} 的还原映射。`);
        const source = endpoint(value);
        if (!source) throw new Error(`隐藏组输出 ${index} 没有有效来源。`);
        for (const id of links) {
            const link = graph.links[id];
            const target = link && graph.getNodeById(link.target_id);
            const input = target?.inputs?.[link.target_slot];
            if (!input || target === group) throw new Error("隐藏组外部输出连接无效。");
            connections.push({ source, target, inputName: input.name });
        }
    }
    // Backend emits dependencies first. Lay out columns by dependency depth.
    const depths = new Map(), rows = new Map(), widths = new Map();
    for (const { node, spec } of nodes.values()) {
        const parents = Object.values(spec.inputs).filter(v => v.kind === "link");
        const depth = parents.reduce((max, v) => Math.max(max, (depths.get(v.node) ?? 0) + 1), 0);
        depths.set(spec.id, depth);
        const row = rows.get(depth) ?? 0;
        node.pos = [group.pos[0], group.pos[1] + row];
        node.setSize?.([Math.max(node.size[0], 320), node.size[1]]);
        widths.set(depth, Math.max(widths.get(depth) ?? 0, node.size[0]));
        rows.set(depth, row + Math.max(node.size[1], 120) + 60);
    }
    const columns = new Map();
    let x = group.pos[0];
    for (const depth of [...widths.keys()].sort((a, b) => a - b)) {
        columns.set(depth, x);
        x += widths.get(depth) + 100;
    }
    for (const { node, spec } of nodes.values()) node.pos[0] = columns.get(depths.get(spec.id));
    return { nodes, connections };
}

export function applyRestoration(graph, group, prepared) {
    for (const { node } of prepared.nodes.values()) graph.add(node);
    for (const { source, target, inputName } of prepared.connections) {
        // Resolve names at connection time: variadic node callbacks can change slots.
        const slot = target.inputs?.findIndex(i => i.name === inputName) ?? -1;
        if (slot < 0) throw new Error(`连接时找不到输入 ${inputName}。`);
        const link = source.node.connect(source.slot, target, slot);
        if (!link) throw new Error(`无法连接 ${source.node.title} → ${target.title}.${inputName}，端口类型可能不兼容。`);
    }
    // Some extensions reject/rewrite connections inside onConnectionsChange.
    for (const { source, target, inputName } of prepared.connections) {
        const input = target.inputs.find(i => i.name === inputName);
        const link = input && graph.links[input.link];
        if (!link || link.origin_id !== source.node.id || link.origin_slot !== source.slot) {
            throw new Error(`节点扩展未保留 ${target.title}.${inputName} 的连线。`);
        }
    }
    graph.remove(group);
    return prepared.nodes.size;
}
