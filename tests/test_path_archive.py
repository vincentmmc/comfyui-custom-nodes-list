import importlib.util
import errno
import json
import os
from pathlib import Path
import sys
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import zipfile

spec = importlib.util.spec_from_file_location('path_archive_test_module', Path(__file__).resolve().parents[1] / 'path_archive.py')
module = importlib.util.module_from_spec(spec)
fake_paths = types.ModuleType('folder_paths')
with patch.dict(sys.modules, {'folder_paths': fake_paths}):
    spec.loader.exec_module(module)


class PathArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'
        fake_paths.get_output_directory = lambda: str(self.output)
        self.node = module.ServerPathArchive()

    def archive(self, result):
        self.assertTrue(result['result'][0])
        url = result['result'][2]
        filename = parse_qs(urlparse(url).query)['filename'][0]
        self.assertEqual(result['ui']['server_path_archive'], [filename])
        return zipfile.ZipFile(self.output / filename)

    def test_single_file_and_download(self):
        source = self.root / '中文 file.bin'
        source.write_bytes(b'\0data\xff')
        with self.archive(self.node.pack('"' + str(source) + '"')) as archive:
            self.assertEqual(archive.read(source.name), source.read_bytes())
            self.assertIsNone(archive.testzip())

    def test_directory_empty_dirs_and_no_extension_filter(self):
        source = self.root / 'folder'
        (source / 'empty').mkdir(parents=True)
        (source / 'model.safetensors').write_bytes(b'model')
        (source / '.env').write_text('test fixture', encoding='utf-8')
        with self.archive(self.node.pack(str(source))) as archive:
            self.assertIn('folder/empty/', archive.namelist())
            self.assertEqual(archive.read('folder/model.safetensors'), b'model')
            self.assertIn('folder/.env', archive.namelist())

    def test_missing_and_relative(self):
        for path in [str(self.root / 'missing'), 'relative/path', '']:
            result = self.node.pack(path)
            self.assertFalse(result['result'][0])
            self.assertEqual(result['result'][2], '')
            self.assertEqual(result['ui']['server_path_archive'], [''])
        self.assertFalse(self.output.exists())

    def test_oversize_failure_removes_partial_zip(self):
        source = self.root / 'large'
        source.write_bytes(b'x' * (1024**2 + 1))
        result = self.node.pack(str(source), max_file_mb=1)
        self.assertTrue(result['result'][0])
        self.assertEqual(result['result'][2], '')
        self.assertEqual(list(self.output.iterdir()), [])

    def test_total_limit_and_unreadable(self):
        source = self.root / 'folder'
        source.mkdir()
        for name in ['a', 'b']:
            (source / name).write_bytes(b'x' * 600000)
        result = self.node.pack(str(source), max_total_mb=1)
        self.assertEqual(result['result'][2], '')
        self.assertEqual(list(self.output.iterdir()), [])
        original = module.os.open
        def open_file(path, *args, **kwargs):
            if Path(path).parent == source:
                raise PermissionError('test access denied')
            return original(path, *args, **kwargs)
        with patch.object(module.os, 'open', side_effect=open_file):
            result = self.node.pack(str(source))
        self.assertEqual(result['result'][2], '')
        self.assertIn('test access denied', result['result'][1])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_output_directory_does_not_include_own_archive(self):
        self.output.mkdir()
        (self.output / 'existing.txt').write_text('hello')
        with self.archive(self.node.pack(str(self.output))) as archive:
            self.assertEqual(archive.read('output/existing.txt'), b'hello')
            self.assertFalse(any(name.endswith('.part') or name.endswith('.zip') for name in archive.namelist()))

    def test_symlink_skipped_and_reported(self):
        source = self.root / 'folder'
        source.mkdir()
        target = self.root / 'outside.txt'
        target.write_text('outside')
        try:
            (source / 'link').symlink_to(target)
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        with self.archive(self.node.pack(str(source))) as archive:
            self.assertNotIn('folder/link', archive.namelist())
            report = json.loads(archive.read(next(n for n in archive.namelist() if n.startswith('EXPORT_REPORT_'))))
            self.assertEqual(len(report['skipped']), 1)

    def test_input_file_link_reports_target_without_archiving(self):
        target = self.root / 'real.txt'
        target.write_text('actual content')
        alias = self.root / 'alias'
        original_stat, original_resolve = Path.lstat, Path.resolve
        def lstat(path):
            return types.SimpleNamespace(st_mode=stat.S_IFLNK) if path == alias else original_stat(path)
        def resolve(path, *args, **kwargs):
            return target if path == alias else original_resolve(path, *args, **kwargs)
        with patch.object(Path, 'lstat', lstat), patch.object(Path, 'resolve', resolve):
            result = self.node.pack(str(alias))
        self.assertIn(str(alias), result['result'][1])
        self.assertIn(str(target), result['result'][1])
        self.assertEqual(result['ui']['server_path_resolved'], [str(target)])
        self.assertEqual(result['result'][2], '')
        self.assertFalse(self.output.exists())
        with self.archive(self.node.pack(str(target))) as archive:
            self.assertEqual(archive.read('real.txt'), b'actual content')

    def test_input_link_resolution_errors(self):
        alias = self.root / 'alias'
        for error, expected in [(FileNotFoundError(), '目标不存在'),
                                (RuntimeError(), '循环链接'),
                                (OSError(errno.ELOOP, 'loop'), '循环链接'),
                                (PermissionError('denied'), '权限不足')]:
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFLNK)), \
                        patch.object(Path, 'resolve', side_effect=error):
                    result = self.node.pack(str(alias))
                self.assertTrue(result['result'][0])
                self.assertIn(expected, result['result'][1])
                self.assertEqual(result['result'][2], '')
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_real_windows_junction(self):
        target = self.root / 'target'
        target.mkdir()
        (target / 'content.txt').write_text('junction content')
        alias = self.root / 'junction'
        environment = dict(os.environ, ARCHIVE_TEST_ALIAS=str(alias), ARCHIVE_TEST_TARGET=str(target))
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                        'New-Item -ItemType Junction -Path $env:ARCHIVE_TEST_ALIAS -Target $env:ARCHIVE_TEST_TARGET -ErrorAction Stop | Out-Null'],
                       env=environment, check=True, capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            result = self.node.pack(str(alias))
            self.assertIn('真实目标', result['result'][1])
            self.assertEqual(result['ui']['server_path_resolved'], [str(target)])
            self.assertEqual(result['result'][2], '')
            self.assertFalse(self.output.exists())
            with self.archive(self.node.pack(str(target))) as archive:
                self.assertEqual(archive.read('target/content.txt'), b'junction content')
        finally:
            # Remove only the junction entry, never recurse into its target.
            alias.rmdir()


if __name__ == '__main__':
    unittest.main()
