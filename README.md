# ComfyUI 自定义节点文件列表

在 **ComfyUI 所在服务器** 列出配置的 `custom_nodes` 目录。无第三方 Python 依赖。

## 安装

1. 解压安装包，将整个 `comfyui-custom-nodes-list` 文件夹上传到远程机器的 `ComfyUI/custom_nodes/`。
2. 确认文件结构如下，避免重复套一层目录：

   ```text
   ComfyUI/custom_nodes/comfyui-custom-nodes-list/
       __init__.py
       README.md
       web/
           file_list.js
   ```

3. 重启远程 ComfyUI 服务，然后刷新浏览器页面（必要时 Ctrl+F5）。
4. 双击画布，搜索 `打印自定义节点文件列表` 或 `CustomNodesFileList`，添加节点。
5. 点击运行。此节点可以单独运行，无需模型或其他节点。

结果显示在节点文本框中，可选中复制；同时通过 `file_list` STRING 输出端口传递，并默认打印到服务器控制台。若前端版本不兼容，可接其他文本显示节点查看 STRING 输出，或查看服务器日志。

只有网页链接不代表拥有服务器上传权限。需要通过云平台文件管理器或 SSH 上传到运行该 ComfyUI 实例的机器/容器。无需把网址填写进插件。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| recursive | true | 是否展开子目录 |
| max_depth | 3 | 最大展开层级；1 表示仅 custom_nodes 的直接子项，最大 20 |
| include_hidden | true | 是否包含以点开头的名称，例如 `.git`；不检查 Windows 隐藏属性 |
| max_entries | 5000 | 所有根目录累计条目上限，最大 100000；超出会明确显示截断 |
| print_to_console | true | 是否同时输出到服务器控制台 |

`[DIR]` 是文件夹，`[FILE]` 是文件，`[LINK]` 是符号链接或 Windows 重解析点。链接只列名称，不展开。输出包含根目录绝对路径，不读取文件正文，不修改服务器文件，不新增 HTTP 接口。条目按文件系统顺序显示；每次运行重新扫描。不可访问的目录会显示错误并继续其他条目。该功能列出磁盘条目，不代表对应节点已经成功加载。

使用 ComfyUI 官方支持的 V1 节点接口：
https://docs.comfy.org/custom-nodes/backend/server_overview
