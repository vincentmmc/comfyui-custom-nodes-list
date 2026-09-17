"""List the custom_nodes directories configured on the ComfyUI server."""

import os
import stat

import folder_paths


class CustomNodesFileList:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "recursive": ("BOOLEAN", {"default": True}),
            "max_depth": ("INT", {"default": 3, "min": 1, "max": 20}),
            "include_hidden": ("BOOLEAN", {"default": True}),
            "max_entries": ("INT", {"default": 5000, "min": 1, "max": 100000}),
            "print_to_console": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_list",)
    FUNCTION = "list_files"
    CATEGORY = "工具/文件列表"
    OUTPUT_NODE = True
    DESCRIPTION = "列出服务器 custom_nodes 中的文件和文件夹。只读取名称，不读取文件正文。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # The filesystem can change without any widget changing.
        return float("nan")

    def list_files(self, recursive=True, max_depth=3, include_hidden=True,
                   max_entries=5000, print_to_console=True):
        max_depth = max(1, min(20, int(max_depth)))
        max_entries = max(1, min(100000, int(max_entries)))
        roots = list(dict.fromkeys(os.path.abspath(p) for p in
                                  folder_paths.get_folder_paths("custom_nodes")))
        lines = ["ComfyUI custom_nodes 文件列表", ""]
        count = 0
        truncated = False

        def walk(directory, depth):
            nonlocal count, truncated
            indent = "  " * depth
            had_entries = False
            try:
                # Streaming iteration keeps memory bounded even for huge folders.
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if not include_hidden and entry.name.startswith("."):
                            continue
                        had_entries = True
                        if count >= max_entries:
                            truncated = True
                            return
                        count += 1
                        try:
                            attrs = entry.stat(follow_symlinks=False)
                            is_link = entry.is_symlink() or bool(
                                getattr(attrs, "st_file_attributes", 0) &
                                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                            )
                            is_dir = entry.is_dir(follow_symlinks=False)
                            kind = "LINK" if is_link else "DIR" if is_dir else "FILE"
                            # repr keeps newlines and control characters in names on one line.
                            lines.append(f"{indent}[{kind}] {entry.name!r}")
                            if is_dir and not is_link and recursive:
                                if depth < max_depth:
                                    walk(entry.path, depth + 1)
                                else:
                                    lines.append(f"{indent}  [已达最大深度，未展开]")
                            if truncated:
                                return
                        except OSError as exc:
                            lines.append(f"{indent}[无法读取] {entry.name!r}: {exc}")
            except OSError as exc:
                lines.append(f"{indent}[无法访问目录] {exc}")
                return
            if not had_entries:
                lines.append(f"{indent}(空目录或无符合条件的条目)")

        if not roots:
            lines.append("没有配置 custom_nodes 路径。")
        for root in roots:
            lines.append(f"根目录: {root}")
            walk(root, 1)
            lines.append("")
            if truncated:
                lines.append(f"[列表已截断：达到 {max_entries} 条上限，后续内容未扫描]")
                break
        lines.append(f"已列出 {count} 个文件/文件夹/链接。")
        text = "\n".join(lines)
        if print_to_console:
            print(text)
        return {"ui": {"text": [text]}, "result": (text,)}


from .archive_nodes import CustomNodesArchive

NODE_CLASS_MAPPINGS = {"CustomNodesFileList": CustomNodesFileList,
                       "CustomNodesArchive": CustomNodesArchive}
NODE_DISPLAY_NAME_MAPPINGS = {"CustomNodesFileList": "打印自定义节点文件列表",
                               "CustomNodesArchive": "打包下载全部 custom_nodes"}
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
