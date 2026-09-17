"""Export configured custom-node roots, with explicit exclusions and size limits."""
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlencode

import folder_paths


SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.ipynb_checkpoints',
             '.venv', 'venv', 'env', 'node_modules', '.cache', 'cache',
             'models', 'checkpoints', 'weights', 'output', 'outputs',
             '.ssh', '.aws', '.azure', '.config'}
SKIP_SUFFIXES = {'.pyc', '.pyo', '.safetensors', '.ckpt', '.pt', '.pth',
                 '.onnx', '.gguf', '.bin', '.engine', '.zip', '.7z', '.rar',
                 '.tar', '.gz', '.log', '.ini', '.pem', '.key', '.p12',
                 '.pfx', '.sqlite', '.sqlite3', '.db'}


def exclusion(path, is_dir):
    name = path.name.lower()
    if is_dir and name in SKIP_DIRS:
        return 'cache/model/environment/private directory'
    if name == '.env' or name.startswith('.env.'):
        return 'environment configuration'
    if any(word in name for word in ('secret', 'credential', 'cookie', 'api_key', 'apikey')):
        return 'possible credentials'
    if name in {'id_rsa', 'id_ed25519', '.netrc', '.npmrc', '.pypirc', '.git-credentials'}:
        return 'credentials'
    if not is_dir:
        if path.suffix.lower() in SKIP_SUFFIXES:
            return 'excluded file type'
        if path.suffix.lower() in {'.json', '.yaml', '.yml', '.toml', '.cfg', '.txt'}:
            if any(word in name for word in ('config', 'setting', 'account', 'token', 'auth')):
                return 'possible private configuration'
    return None


class CustomNodesArchive:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'max_total_mb': ('INT', {'default': 2048, 'min': 1, 'max': 16384}),
            'max_file_mb': ('INT', {'default': 100, 'min': 1, 'max': 1024}),
        }}

    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('download_info',)
    FUNCTION = 'pack'
    CATEGORY = '工具/文件列表'
    OUTPUT_NODE = True
    DESCRIPTION = '打包所有已配置的 custom_nodes 根目录；排除缓存、权重和常见凭据配置，跳过链接。ZIP 内含排除清单。'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def pack(self, max_total_mb=2048, max_file_mb=100):
        total_limit = max(1, min(16384, int(max_total_mb))) * 1024 * 1024
        file_limit = max(1, min(1024, int(max_file_mb))) * 1024 * 1024
        roots = list(dict.fromkeys(Path(p).resolve() for p in
                                  folder_paths.get_folder_paths('custom_nodes')))
        if not roots:
            raise ValueError('没有配置 custom_nodes 目录。')
        output = Path(folder_paths.get_output_directory()).resolve()
        output.mkdir(parents=True, exist_ok=True)
        filename = 'custom_nodes_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex + '.zip'
        fd, temporary = tempfile.mkstemp(prefix='.custom_nodes_', suffix='.part', dir=output)
        os.close(fd)
        report = {'roots': [], 'excluded': [], 'errors': [], 'files': 0, 'source_bytes': 0,
                  'note': 'Filtered source export, not a complete backup. Filenames cannot detect secrets embedded in code. Symlinks/reparse points are not followed.'}
        visited = 0

        def walk(archive, directory, root, prefix):
            nonlocal visited
            try:
                entries = os.scandir(directory)
            except OSError as exc:
                report['errors'].append({'path': str(directory.relative_to(root)), 'error': str(exc)})
                return
            with entries:
                for entry in entries:
                    visited += 1
                    if visited > 200000:
                        raise ValueError('扫描条目超过 200000；已停止并删除未完成的 ZIP。')
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    archive_name = prefix + '/' + relative
                    try:
                        info = path.lstat()
                        reason = None
                        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                            reason = 'symlink/reparse point'
                        elif not path.resolve().is_relative_to(root):
                            reason = 'outside configured root'
                        elif path.resolve() == output or output in path.resolve().parents:
                            reason = 'output directory'
                        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                            reason = 'not a regular file/directory'
                        else:
                            reason = exclusion(path, stat.S_ISDIR(info.st_mode))
                        if reason:
                            report['excluded'].append({'path': archive_name, 'reason': reason})
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            archive.writestr(archive_name + '/', b'')
                            walk(archive, path, root, prefix)
                            continue
                        if info.st_size > file_limit:
                            report['excluded'].append({'path': archive_name, 'reason': 'per-file size limit'})
                            continue
                        if report['source_bytes'] + info.st_size > total_limit:
                            raise ValueError('文件总大小超过 max_total_mb；已停止并删除未完成的 ZIP，请提高上限后重试。')
                        # Refuse leaf symlink replacement on platforms supporting O_NOFOLLOW.
                        src_fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
                        with os.fdopen(src_fd, 'rb') as source:
                            opened = os.fstat(source.fileno())
                            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                                raise OSError('File changed while opening')
                            written = 0
                            with archive.open(archive_name, 'w', force_zip64=True) as target:
                                while True:
                                    block = source.read(1024 * 1024)
                                    if not block:
                                        break
                                    written += len(block)
                                    if written > file_limit or report['source_bytes'] + written > total_limit:
                                        raise ValueError('文件在打包时增长并超过上限，已停止；请在目录稳定后重试。')
                                    target.write(block)
                        report['source_bytes'] += written
                        report['files'] += 1
                    except OSError as exc:
                        # Abort rather than publishing an archive containing a partial file.
                        raise OSError(f'无法完整打包 {archive_name}: {exc}') from exc

        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for index, root in enumerate(roots, 1):
                    if not root.is_dir():
                        raise ValueError(f'custom_nodes 根目录不可访问: {root}')
                    prefix = 'custom_nodes' if len(roots) == 1 else f'custom_nodes_{index}'
                    report['roots'].append({'path': str(root), 'archive_folder': prefix})
                    walk(archive, root, root, prefix)
                archive.writestr('EXPORT_MANIFEST.json', json.dumps(report, ensure_ascii=False, indent=2))
            os.replace(temporary, output / filename)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        query = urlencode({'filename': filename, 'type': 'output'})
        message = (f"已打包 {report['files']} 个文件，原始大小 {report['source_bytes'] / 1024**2:.1f} MiB。\n"
                   f"排除 {len(report['excluded'])} 项；无法遍历的目录 {len(report['errors'])} 个。\n"
                   '详见 ZIP 内 EXPORT_MANIFEST.json。此包不是完整环境备份。\n'
                   f'下载路径（加在 ComfyUI 服务地址后）：/view?{query}')
        return {'ui': {'text': [message], 'custom_nodes_archive': [filename]}, 'result': (message,)}
