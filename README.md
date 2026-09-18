# ComfyUI 自定义节点文件列表

在 **ComfyUI 所在服务器** 列出配置的 `custom_nodes` 目录，并提供打包下载和隐藏节点组还原功能。文件列表与打包功能无第三方 Python 依赖；还原功能需要 `cryptography`。

## 还原隐藏节点组为普通节点

1. 将新版插件文件夹上传到运行 ComfyUI 的服务器，覆盖旧版插件文件。
2. 使用 **ComfyUI 自己的 Python 环境** 执行 `python -m pip install -r requirements.txt`（在本插件目录运行）。
3. 重启 ComfyUI，刷新页面（必要时 Ctrl+F5）。
4. 在主画布右键点击 `LamGroupNode`（通常显示为 `GroupNode`，也可能被重命名），选择 **还原成普通节点（含嵌套组）**。

服务器在 `/custom_nodes_list/restore_lam_group` 解密并生成展开计划，不执行内部节点，不使用 `/wanaq/encipher`。浏览器创建普通节点、恢复参数、内部连线与外部输入输出，最后移除原隐藏组。嵌套的 `LamGroupNode` 自动递归展开，节点按依赖关系排列；原始位置、颜色、分组未保存在密文中，无法恢复。只恢复原执行逻辑中可从导出端口追溯到的节点，避免启用原来未参与执行的节点。

- 支持当前 `ComfyUI_GroupNode` 的内置密钥格式；AES-GCM 认证失败会停止，不绕过完整性校验。
- 每次替换前自动下载 `before_restore_时间戳.json` 工作流备份。失败时会尝试恢复原工作流；若浏览器自动恢复失败，可手动导入备份。
- 缺少节点类型、参数名称不兼容或连线失败时明确报错，不会静默跳过。仍需安装内部节点对应的插件与模型。
- 连接期间第三方节点可能调整动态端口，插件会检查最终连接是否保留；不保证适配所有第三方节点的自定义控件和动态端口行为。
- 暂不支持 ComfyUI 原生子图内部的隐藏组；Bypass 状态的组需先取消 Bypass。静音组展开后保持静音。
- 还原不需要运行工作流；解密 JSON 不包含 `eval`、`exec` 或模型调用。
- 如只需检查数据，可使用独立脚本：`python decode_hidden_json.py workflow.json --node-id 81 -o decoded.json`；也支持输入仅包含密文的 TXT。

验证：`python -m unittest discover -s tests -p test_restore.py -v`，以及 `node tests/test_restore.mjs`。

## 打包下载全部 custom_nodes

更新本插件并重启 ComfyUI、刷新页面后，搜索 **打包下载全部 custom_nodes**（`CustomNodesArchive`）。
单独运行该节点，完成后点击节点内的 **下载 custom_nodes ZIP** 链接。

- 扫描所有已配置的 custom_nodes 根目录，保留子目录结构；多根目录分别放入 `custom_nodes_1`、`custom_nodes_2` 等目录。
- 默认最多打包 2048 MiB 原始文件，单文件上限 100 MiB；可通过节点参数调整。单文件过大则跳过，总大小超限则报错并删除本次未完成的包。
- 排除 Git 历史、缓存、虚拟环境、node_modules、模型目录/权重、已有压缩包及常见凭据配置文件。跳过符号链接和 Windows 重解析点。
- ZIP 根目录的 `EXPORT_MANIFEST.json` 列出根路径、排除项和无法遍历的目录。被排除的目录不会逐项枚举其内部文件。
- 扫描后、获取文件信息或打开文件前消失的文件会跳过，并记录在清单的 `errors` 中；其他文件继续打包。已开始写入 ZIP 后的读取/写入错误仍中止任务，避免生成含不完整文件的压缩包。
- ZIP 保存在 ComfyUI 的 output 根目录，使用现有 `/view` 接口下载；没有新增下载接口。每次运行生成新的文件，旧文件需要自行清理。
- 这是经过过滤的源码导出，**不是完整环境备份**；不会保证依赖、配置和模型可直接恢复。
- 文件名过滤不能识别代码或工作流中硬编码的密钥。下载包可能仍含私有源码或敏感信息，请勿公开上传。ZIP 继承 ComfyUI 输出文件的访问权限，不提供独立鉴权或自动过期。

如果节点内未显示下载链接，可以使用 STRING 输出里的 `/view?...` 路径，在前面加上当前 ComfyUI 服务地址。旧前端可能需要 Ctrl+F5 才能加载新增脚本。

Git 安装地址：https://github.com/vincentmmc/comfyui-custom-nodes-list

## 安装

1. 解压安装包，将整个 `comfyui-custom-nodes-list` 文件夹上传到远程机器的 `ComfyUI/custom_nodes/`。
2. 确认文件结构如下，避免重复套一层目录：

   ```text
   ComfyUI/custom_nodes/comfyui-custom-nodes-list/
       __init__.py
       archive_nodes.py
       restore_group.py
       decode_hidden_json.py
       requirements.txt
       README.md
       web/
           file_list.js
           archive_download.js
           restore_group.js
           restore_plan.js
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
