import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { prepareRestoration, applyRestoration } from "./restore_plan.js";

let restoring = false;

function downloadBackup(snapshot) {
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `before_restore_${Date.now()}.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function restoreNode(group) {
    if (restoring) return;
    restoring = true;
    let snapshot, changed = false;
    try {
        if (group.graph !== app.graph) throw new Error("请先进入主画布操作；暂不支持原生子图内部的隐藏组。");
        if (group.mode === 4) throw new Error("请先取消该隐藏组的 Bypass，再还原。");
        const graph = group.graph;
        const ciphertext = group.properties?.hiddenJson || group.widgets?.find(w => w.name === "hiddenJson")?.value;
        if (!ciphertext) throw new Error("该节点没有 hiddenJson 数据。");
        const response = await api.fetchApi("/custom_nodes_list/restore_lam_group", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hiddenJson: ciphertext }),
        });
        if (response.status === 404) throw new Error("还原接口不存在，请更新服务器插件并重启 ComfyUI。");
        const plan = await response.json();
        if (!response.ok || !plan.success) throw new Error(plan.error || "服务器解码失败。");
        // Old frontends need widget conversion; new frontends already expose slots.
        let convertToInput;
        try {
            ({ convertToInput } = await import("../../extensions/core/widgetInputs.js"));
        } catch { /* Missing slots get an explicit compatibility error below. */ }
        if (app.graph !== graph || graph.getNodeById(group.id) !== group) {
            throw new Error("等待解码期间工作流已切换或节点已删除，请重新操作。");
        }
        const current = group.properties?.hiddenJson || group.widgets?.find(w => w.name === "hiddenJson")?.value;
        if (current !== ciphertext) throw new Error("等待期间隐藏组数据发生变化，请重新操作。");
        snapshot = JSON.parse(JSON.stringify(graph.serialize()));
        // Preparation checks all classes, parameter names and endpoints before mutation.
        const prepared = prepareRestoration(graph, group, plan, LiteGraph, convertToInput);
        downloadBackup(snapshot);
        graph.beforeChange?.();
        changed = true;
        const count = applyRestoration(graph, group, prepared);
        graph.afterChange?.();
        app.canvas.setDirty(true, true);
        alert(`已还原为 ${count} 个普通节点。还原前的工作流备份已下载。`);
    } catch (error) {
        console.error("[custom_nodes_list] restore failed", error);
        let status = "原隐藏组未替换。";
        if (changed && snapshot) {
            try {
                await app.loadGraphData(snapshot);
                status = "已恢复还原前的工作流。";
            } catch (rollbackError) {
                console.error("[custom_nodes_list] rollback failed", rollbackError);
                status = "自动恢复失败，请导入刚刚下载的 before_restore 工作流备份。";
            }
        }
        alert(`还原失败：${error.message}\n${status}`);
    } finally {
        restoring = false;
    }
}

app.registerExtension({
    name: "custom_nodes_file_list.restore_lam_group",
    // Also works for a loaded placeholder node if the original extension is absent.
    nodeCreated(node) {
        if (node.comfyClass !== "LamGroupNode" && node.type !== "LamGroupNode") return;
        const original = node.getExtraMenuOptions;
        node.getExtraMenuOptions = function (canvas, options) {
            const result = original?.apply(this, arguments);
            options.push({
                content: "还原成普通节点（含嵌套组）",
                disabled: restoring,
                callback: () => restoreNode(this),
            });
            return result;
        };
    },
});
