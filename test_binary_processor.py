"""Boundary, differential, validation, and safe-writing tests."""
import errno
import itertools
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch

import binary_processor as bp


class ConversionTests(unittest.TestCase):
    def test_old(self):
        self.assertEqual(bp.decimal_to_little_endian(10100400),
                         struct.pack('<I', 10100400))
        self.assertEqual(len(bp.decimal_to_little_endian(10100400)), 4)

    def test_new(self):
        self.assertEqual(bp.decimal_to_little_endian(101004046),
                         struct.pack('<I', 101004046))

    def test_bounds(self):
        self.assertEqual(bp.decimal_to_little_endian(0), b'\0' * 4)
        self.assertEqual(bp.decimal_to_little_endian(2**32 - 1), b'\xff' * 4)

    def test_negative(self):
        with self.assertRaises(ValueError):
            bp.decimal_to_little_endian(-1)

    def test_overflow(self):
        with self.assertRaises(ValueError):
            bp.decimal_to_little_endian(2**32)

    def test_types(self):
        for value in (True, False, 1.2, '123', None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                bp.decimal_to_little_endian(value)

    def test_hex(self):
        self.assertEqual(bp.format_hex(b'\x12\xab\x34\xcd'), '12 AB 34 CD')
        self.assertEqual(bp.format_hex(b''), '')


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / 'sample.pak'
        self.out = self.root / 'output.pak'
        self.old = struct.pack('<I', 10100400)
        self.new = struct.pack('<I', 101004046)
        mock = patch.object(bp.logger, 'exception')
        mock.start()
        self.addCleanup(mock.stop)

    def run_case(self, data, chunk=8 * 1024 * 1024, old=None, expected=None):
        old = self.old if old is None else old
        self.src.write_bytes(data)
        self.out.unlink(missing_ok=True)
        count = bp.replace_binary_ids(
            self.src, self.out, int.from_bytes(old, 'little'), 101004046, chunk)
        self.assertEqual(count, data.count(old))
        self.assertEqual(self.out.read_bytes(),
                         data.replace(old, self.new)
                         if expected is None else expected)
        self.assertEqual(self.src.read_bytes(), data)
        self.assertEqual(self.src.stat().st_size,
                         self.out.stat().st_size)
        self.assertEqual(list(self.root.glob('.binary-id-*')), [])
        return count

    def test_single(self):
        self.assertEqual(self.run_case(b'prefix' + self.old + b'tail'), 1)

    def test_multiple(self):
        self.assertEqual(self.run_case((b'abc' + self.old) * 12), 12)

    def test_no_match(self):
        self.assertEqual(self.run_case(b'unrelated'), 0)

    def test_beginning(self):
        self.run_case(self.old + b'abc')

    def test_end(self):
        self.run_case(b'abc' + self.old)

    def test_chunk_boundary(self):
        self.assertEqual(self.run_case(b'x' * 8 + self.old + b'tail', 10), 1)

    def test_multiple_boundaries(self):
        self.assertEqual(self.run_case(b'x' * 8 + self.old + b'x' * 6 +
                                      self.old + b'x' * 7 + self.old, 10), 3)

    def test_all_alignments(self):
        for chunk in range(1, 18):
            for pos in range(2 * chunk + 1):
                with self.subTest(chunk=chunk, pos=pos):
                    self.run_case(b'x' * pos + self.old * 3 + b'y' * 9, chunk)

    def test_empty_short(self):
        for size in range(4):
            self.run_case(b'x' * size, 1)

    def test_unrelated_bytes(self):
        rng = random.Random(42)
        data = bytearray(rng.getrandbits(8) for _ in range(5000))
        expected = data.copy()
        for pos in (0, 9, 126, 1023, 2500, 4996):
            data[pos:pos + 4] = self.old
            expected[pos:pos + 4] = self.new
        self.run_case(bytes(data), 127, expected=bytes(expected))

    def test_overlap(self):
        for old in (b'aaaa', b'abab', b'aaba', b'\0' * 4):
            for chunk in range(1, 12):
                self.run_case(old * 9 + old[:3], chunk, old)

    def test_exhaustive_short_inputs(self):
        for length in range(9):
            for values in itertools.product((0, 1), repeat=length):
                self.run_case(bytes(values), 1 + length % 5, b'\0' * 4)

    def test_invalid_ids(self):
        self.src.write_bytes(self.old)
        for old, new in ((-1, 1), (1, 2**32), (True, 2),
                         (1, False), (1, 1)):
            with self.assertRaises((ValueError, TypeError)):
                bp.replace_binary_ids(self.src, self.out, old, new)
        self.assertFalse(self.out.exists())

    def test_invalid_chunk(self):
        self.src.write_bytes(self.old)
        for chunk in (0, -1, True, 1.5, '10', None):
            with self.assertRaises((ValueError, TypeError)):
                bp.replace_binary_ids(self.src, self.out, 1, 2, chunk)

    def test_missing(self):
        with self.assertRaises(FileNotFoundError):
            bp.replace_binary_ids(self.src, self.out, 1, 2)

    def test_directory(self):
        with self.assertRaisesRegex(ValueError, 'not a file'):
            bp.replace_binary_ids(self.root, self.out, 1, 2)

    def test_same(self):
        self.src.write_bytes(self.old)
        with self.assertRaisesRegex(ValueError, 'same file'):
            bp.replace_binary_ids(self.src, self.src, 1, 2)
        self.assertEqual(self.src.read_bytes(), self.old)

    def test_alias(self):
        self.src.write_bytes(self.old)
        try:
            os.link(self.src, self.out)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Hard links unavailable in test environment: {exc}")
        with self.assertRaisesRegex(ValueError, 'same file'):
            bp.replace_binary_ids(self.src, self.out, 1, 2)

    def test_existing_output(self):
        self.src.write_bytes(self.old)
        self.out.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assertEqual(self.out.read_bytes(), b'keep')

    def test_names(self):
        self.assertEqual(bp.generate_output_path(self.src).name,
                         'sample_modified.pak')
        (self.root / 'sample_modified.pak').touch()
        self.assertEqual(bp.generate_output_path(self.src).name,
                         'sample_modified_2.pak')
        (self.root / 'sample_modified_2.pak').touch()
        self.assertEqual(bp.generate_output_path(self.src).name,
                         'sample_modified_3.pak')
        self.assertEqual(bp.generate_output_path(self.root / 'a').name,
                         'a_modified')

    def assert_clean(self):
        self.assertEqual(self.src.read_bytes(), self.old)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob('.binary-id-*')), [])

    def test_read_denied(self):
        self.src.write_bytes(self.old)
        with patch.object(Path, 'open', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_sync_failure(self):
        self.src.write_bytes(self.old)
        with patch.object(bp.os, 'fsync', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_publish_failure(self):
        self.src.write_bytes(self.old)
        with patch.object(bp, '_publish_file',
                          side_effect=OSError('publish error')):
            with self.assertRaises(OSError):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_publish_race(self):
        self.src.write_bytes(self.old)
        real_publish = bp._publish_file

        def racing_publication(src, dest):
            Path(dest).write_bytes(b'other writer')
            real_publish(src, dest)

        with patch.object(bp, '_publish_file', side_effect=racing_publication):
            with self.assertRaises(FileExistsError):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assertEqual(self.out.read_bytes(), b'other writer')
        self.assertEqual(list(self.root.glob('.binary-id-*')), [])

    def test_size_mismatch(self):
        self.src.write_bytes(self.old)
        real_stat = Path.stat

        def wrong_size(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if path.name.startswith('.binary-id-'):
                fields = list(result)
                fields[6] += 1
                return os.stat_result(fields)
            return result

        with patch.object(Path, 'stat', wrong_size):
            with self.assertRaisesRegex(OSError, 'size verification'):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_default_chunk_boundary(self):
        self.run_case(b'x' * (8 * 1024 * 1024 - 2) + self.old + b'end')

    def test_final_size_failure(self):
        self.src.write_bytes(self.old)
        real_publish = bp._publish_file

        def corrupt_publication(src, dest):
            real_publish(src, dest)
            with Path(dest).open('ab') as stream:
                stream.write(b'extra')

        with patch.object(bp, '_publish_file', side_effect=corrupt_publication):
            with self.assertRaisesRegex(OSError, 'differs'):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_normal_publication(self):
        with patch.object(bp.shutil, 'copyfileobj',
                          wraps=bp.shutil.copyfileobj) as copy:
            self.assertEqual(self.run_case(self.old * 3), 3)
        copy.assert_called_once()

    def test_unsupported_fsync(self):
        for code in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP):
            with self.subTest(errno=code):
                with patch.object(bp.os, 'fsync',
                                  side_effect=OSError(code, 'unsupported')):
                    with self.assertLogs(bp.logger, 'WARNING'):
                        self.assertEqual(self.run_case(self.old), 1)

    def test_real_sync_error_is_not_ignored(self):
        self.src.write_bytes(self.old)
        with patch.object(bp.os, 'fsync',
                          side_effect=OSError(errno.EIO, 'I/O error')):
            with self.assertRaises(OSError) as error:
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assertEqual(error.exception.errno, errno.EIO)
        self.assert_clean()

    def test_missing_output_directory(self):
        self.src.write_bytes(self.old)
        with self.assertRaisesRegex(FileNotFoundError, 'Output directory'):
            bp.replace_binary_ids(self.src, self.root / 'missing' / 'a', 1, 2)
        self.assert_clean()

    def test_output_parent_is_file(self):
        self.src.write_bytes(self.old)
        with self.assertRaisesRegex(NotADirectoryError, 'not a directory'):
            bp.replace_binary_ids(self.src, self.src / 'a', 1, 2)
        self.assert_clean()

    def test_unwritable_output_directory(self):
        self.src.write_bytes(self.old)
        with patch.object(bp.os, 'access', return_value=False):
            with self.assertRaisesRegex(PermissionError, 'not writable'):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_directory_creation_denied(self):
        self.src.write_bytes(self.old)
        with patch.object(bp.tempfile, 'NamedTemporaryFile',
                          side_effect=PermissionError('access denied')):
            with self.assertRaisesRegex(OSError, 'output directory'):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_partial_publication_cleanup(self):
        self.src.write_bytes(self.old)

        def fail_copy(source, destination, length):
            destination.write(b'partial')
            raise OSError('disk full')

        with patch.object(bp.shutil, 'copyfileobj', side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, 'disk full'):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_publication_sync_failure_cleanup(self):
        self.src.write_bytes(self.old)
        with patch.object(bp.os, 'fsync',
                          side_effect=[None, OSError('sync failed')]):
            with self.assertRaisesRegex(OSError, 'sync failed'):
                bp.replace_binary_ids(self.src, self.out, 1, 2)
        self.assert_clean()

    def test_logging(self):
        with self.assertLogs(bp.logger, 'INFO') as logs:
            self.run_case(self.old)
        self.assertIn('original_size=4', ' '.join(logs.output))
        self.assertIn('replacements=1 final_size=4', ' '.join(logs.output))


if __name__ == '__main__':
    unittest.main()
