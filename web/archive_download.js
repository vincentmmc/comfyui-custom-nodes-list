import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

app.registerExtension({
    name: "custom_nodes_file_list.archive",
    nodeCreated(node) {
        if (!["CustomNodesArchive", "ServerPathArchive"].includes(node.comfyClass)) return;
        const isPathArchive = node.comfyClass === "ServerPathArchive";
        const status = ComfyWidgets.STRING(node, "archive_status", ["STRING", { multiline: true }], app).widget;
        status.inputEl.readOnly = true;
        status.options = { ...status.options, serialize: false };
        const container = document.createElement("div");
        container.style.padding = "8px";
        const link = document.createElement("a");
        link.textContent = "运行后生成 ZIP 下载链接";
        link.style.color = "#80c7ff";
        container.append(link);
        node.addDOMWidget("archive_download", "custom_nodes_archive", container, { serialize: false });
        const original = node.onExecuted;
        node.onExecuted = function (message) {
            original?.apply(this, arguments);
            status.value = (message?.text ?? []).join("\n");
            const filename = (isPathArchive ? message?.server_path_archive : message?.custom_nodes_archive)?.[0];
            const pattern = isPathArchive ? /^server_path_[a-f0-9]{32}\.zip$/ : /^custom_nodes_[A-Za-z0-9_]+\.zip$/;
            if (typeof filename === "string" && pattern.test(filename)) {
                link.href = api.apiURL("/view?" + new URLSearchParams({ filename, type: "output" }));
                link.download = filename;
                link.textContent = isPathArchive ? "下载指定路径 ZIP（点击保存）" : "下载 custom_nodes ZIP（点击保存）";
            } else {
                link.removeAttribute("href");
                link.textContent = "没有可下载的压缩包";
            }
            this.setDirtyCanvas(true, true);
        };
        node.setSize([560, 360]);
    },
});
