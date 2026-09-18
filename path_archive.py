"""Archive a user-selected absolute server path for download via ComfyUI /view."""
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
import zipfile
from urllib.parse import urlencode

import folder_paths


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


class ServerPathArchive:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'server_path': ('STRING', {'default': '', 'multiline': False}),
            'max_total_mb': ('INT', {'default': 2048, 'min': 1, 'max': 65536}),
            'max_file_mb': ('INT', {'default': 1024, 'min': 1, 'max': 65536}),
        }}

    RETURN_TYPES = ('BOOLEAN', 'STRING', 'STRING')
    RETURN_NAMES = ('exists', 'status', 'download_url')
    FUNCTION = 'pack'
    CATEGORY = '工具/文件列表'
    OUTPUT_NODE = True
    DESCRIPTION = '检查服务器绝对路径并打包文件或目录。递归保留普通文件，不按扩展名过滤；跳过链接。'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def pack(self, server_path, max_total_mb=2048, max_file_mb=1024):
        exists = False
        temporary = None

        def result(message, filename=''):
            url = '/view?' + urlencode({'filename': filename, 'type': 'output'}) if filename else ''
            return {'ui': {'text': [message], 'server_path_archive': [filename]},
                    'result': (exists, message, url)}

        try:
            raw = server_path.strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
                raw = raw[1:-1]
            if not raw:
                return result('请输入服务器上的文件或文件夹绝对路径。')
            path = Path(raw).expanduser()
            if not path.is_absolute():
                return result('请输入服务器绝对路径，例如 /home/ComfyUI/input/image.png 或 D:\\ComfyUI\\input。')
            try:
                info = path.lstat()
            except FileNotFoundError:
                return result(f'路径不存在：{path}')
            exists = True
            if is_link(info):
                return result('路径存在，但它是符号链接或重解析点；请填写真实目标路径。')
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                return result('路径存在，但不是普通文件或文件夹。')
            path = path.resolve(strict=True)
            total_limit = max(1, min(65536, int(max_total_mb))) * 1024**2
            file_limit = max(1, min(65536, int(max_file_mb))) * 1024**2
            output = Path(folder_paths.get_output_directory()).resolve()
            output.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            filename = 'server_path_' + token + '.zip'
            final = output / filename
            fd, temporary = tempfile.mkstemp(prefix='.server_path_', suffix='.part', dir=output)
            os.close(fd)
            temporary = Path(temporary)
            report = {'source': str(path), 'files': 0, 'source_bytes': 0, 'skipped': []}
            visited = 0
            root = path if path.is_dir() else path.parent

            def add(archive, item, name, depth=0):
                nonlocal visited
                visited += 1
                if depth > 128 or visited > 200000:
                    raise ValueError('目录过深或条目超过 200000，请缩小打包范围。')
                if item in (temporary, final):
                    return
                attrs = item.lstat()
                if is_link(attrs):
                    report['skipped'].append({'path': name, 'reason': '链接/重解析点'})
                    return
                if not item.resolve().is_relative_to(root):
                    raise ValueError('扫描路径发生变化并离开目标目录，请重试。')
                if stat.S_ISDIR(attrs.st_mode):
                    archive.writestr(name + '/', b'')
                    with os.scandir(item) as entries:
                        for entry in entries:
                            add(archive, Path(entry.path), name + '/' + entry.name, depth + 1)
                    return
                if not stat.S_ISREG(attrs.st_mode):
                    report['skipped'].append({'path': name, 'reason': '不是普通文件'})
                    return
                if attrs.st_size > file_limit or report['source_bytes'] + attrs.st_size > total_limit:
                    raise ValueError('文件大小超过 max_file_mb 或总大小超过 max_total_mb，请提高上限后重试。')
                fd = os.open(item, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
                with os.fdopen(fd, 'rb') as source:
                    opened = os.fstat(source.fileno())
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (attrs.st_dev, attrs.st_ino):
                        raise ValueError('文件在打开时发生变化，请重试。')
                    written = 0
                    with archive.open(name, 'w', force_zip64=True) as target:
                        while block := source.read(1024 * 1024):
                            written += len(block)
                            if written > file_limit or report['source_bytes'] + written > total_limit:
                                raise ValueError('文件在读取时增长并超过大小上限，请重试。')
                            target.write(block)
                    after = os.fstat(source.fileno())
                    if written != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns:
                        raise ValueError('文件在读取时发生变化，请在文件稳定后重试。')
                report['files'] += 1
                report['source_bytes'] += written

            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                add(archive, path, path.name or 'root')
                archive.writestr('EXPORT_REPORT_' + token + '.json', json.dumps(report, ensure_ascii=False, indent=2))
            os.replace(temporary, final)
            temporary = None
            url = '/view?' + urlencode({'filename': filename, 'type': 'output'})
            message = (f"路径存在，打包完成：{path}\n"
                       f"普通文件 {report['files']} 个，原始大小 {report['source_bytes'] / 1024**2:.2f} MiB；"
                       f"跳过链接或特殊文件 {len(report['skipped'])} 项。\n"
                       f'下载路径（相对于 ComfyUI 服务地址）：{url}')
            return result(message, filename)
        except (OSError, ValueError, RuntimeError) as exc:
            return result(f'检查或打包失败：{exc}\n未生成下载文件。')
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
