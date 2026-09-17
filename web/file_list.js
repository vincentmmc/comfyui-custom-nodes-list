import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

app.registerExtension({
    name: "custom_nodes_file_list.display",
    nodeCreated(node) {
        if (node.comfyClass !== "CustomNodesFileList") return;
        const widget = ComfyWidgets.STRING(
            node, "file_list_preview", ["STRING", { multiline: true }], app
        ).widget;
        widget.inputEl.readOnly = true;
        widget.inputEl.style.fontFamily = "monospace";
        widget.inputEl.placeholder = "点击运行，查看服务器 custom_nodes 文件列表";
        widget.options = { ...widget.options, serialize: false };
        const original = node.onExecuted;
        node.onExecuted = function (message) {
            original?.apply(this, arguments);
            widget.value = (message?.text ?? []).join("\n");
            this.setDirtyCanvas(true, true);
        };
        node.setSize([Math.max(node.size[0], 560), Math.max(node.size[1], 420)]);
    },
});
