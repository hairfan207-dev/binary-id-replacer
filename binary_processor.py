"""Chunked, size-preserving replacement of unsigned 32-bit binary IDs."""

import errno
import logging
import os
from pathlib import Path
import struct
import shutil
import tempfile

logger = logging.getLogger(__name__)


def decimal_to_little_endian(value: int) -> bytes:
    """Encode an integer in the inclusive UINT32 range as four LE bytes."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("ID must be an integer; booleans are not accepted")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("ID must be between 0 and 4294967295 inclusive")
    return struct.pack("<I", value)


def format_hex(data: bytes) -> str:
    """Return uppercase, space-separated hexadecimal bytes."""
    return data.hex(" ").upper()


def generate_output_path(input_path: Path) -> Path:
    """Find an unused sibling name; this does not reserve the name."""
    input_path = Path(input_path)
    index = 1
    while True:
        suffix = "" if index == 1 else f"_{index}"
        candidate = input_path.with_name(
            f"{input_path.stem}_modified{suffix}{input_path.suffix}"
        )
        # lexists also regards dangling symlinks as occupied names.
        if not os.path.lexists(candidate):
            return candidate
        index += 1



def _sync_file(descriptor: int) -> None:
    """Sync writes when supported; propagate actual storage failures."""
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}:
            raise
        logger.warning("Filesystem does not support fsync: %s", exc)


def _publish_file(temporary: Path, output_path: Path) -> None:
    """Copy a verified temporary file into an exclusively created output.

    Exclusive creation rejects existing files, including concurrent creations.
    A failed copy removes only the output created by this call. Unlike a rename,
    the final name is visible during copying; callers must wait for completion.
    """
    created = False
    try:
        with temporary.open("rb") as source:
            with output_path.open("xb") as destination:
                created = True
                shutil.copyfileobj(source, destination, 8 * 1024 * 1024)
                destination.flush()
                _sync_file(destination.fileno())
    except Exception:
        if created:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove partial output: %s",
                                 output_path)
        raise


def replace_binary_ids(
    input_path: Path,
    output_path: Path,
    old_id: int,
    new_id: int,
    chunk_size: int = 8 * 1024 * 1024,
) -> int:
    """Replace non-overlapping IDs, publishing a separate, new output file.

    Existing output paths are rejected. The input must remain unchanged by
    other programs during processing. Memory use is O(chunk_size).
    """
    temporary = None
    published = False
    try:
        input_path = Path(input_path)
        output_path = Path(output_path)
        old = decimal_to_little_endian(old_id)
        new = decimal_to_little_endian(new_id)
        if old_id == new_id:
            raise ValueError("Old ID and New ID must differ")
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise TypeError("chunk_size must be a positive integer")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not input_path.exists():
            raise FileNotFoundError(f"Input file does not exist: {input_path}")
        if not input_path.is_file():
            raise ValueError(f"Input path is not a file: {input_path}")
        if input_path.resolve() == output_path.resolve() or (
            output_path.exists() and input_path.samefile(output_path)
        ):
            raise ValueError(
                "Input and output must not point to the same file"
            )
        if os.path.lexists(output_path):
            raise FileExistsError(f"Output already exists: {output_path}")

        parent = output_path.parent
        if not parent.exists():
            raise FileNotFoundError(f"Output directory does not exist: {parent}")
        if not parent.is_dir():
            raise NotADirectoryError(
                f"Output parent is not a directory: {parent}"
            )
        if not os.access(parent, os.W_OK):
            raise PermissionError(f"Output directory is not writable: {parent}")

        original_size = input_path.stat().st_size
        logger.info(
            "Processing started: input=%s output=%s original_size=%d "
            "old_hex=%s new_hex=%s",
            input_path, output_path, original_size, format_hex(old),
            format_hex(new),
        )
        count = 0
        # Opening the input verifies actual read access, without an os.access
        # check that could disagree with the subsequent open.
        with input_path.open("rb") as source:
            # Actual creation also checks ACLs and permission changes that an
            # advisory os.access check may not detect (especially on Windows).
            try:
                temporary_stream = tempfile.NamedTemporaryFile(
                    mode="wb", prefix=".binary-id-", suffix=".tmp",
                    dir=parent, delete=False,
                )
            except OSError as exc:
                raise OSError(
                    f"Cannot create a temporary file in output directory "
                    f"'{parent}': {exc.strerror or exc}"
                ) from exc
            with temporary_stream as destination:
                temporary = Path(destination.name)
                pending = b""
                while True:
                    chunk = source.read(chunk_size)
                    if not chunk:
                        count += pending.count(old)
                        destination.write(pending.replace(old, new))
                        break
                    data = pending + chunk
                    # Starts before limit have four available bytes. The final
                    # three bytes remain undecided until the next read. A match
                    # may consume bytes beyond limit: retain only bytes AFTER
                    # that match, so no byte is written or replaced twice.
                    limit = max(0, len(data) - 3)
                    cursor = 0
                    while cursor < limit:
                        match = data.find(old, cursor)
                        if match < 0 or match >= limit:
                            break
                        destination.write(data[cursor:match])
                        destination.write(new)
                        count += 1
                        cursor = match + 4
                    if cursor < limit:
                        destination.write(data[cursor:limit])
                    pending = data[max(cursor, limit):]
                destination.flush()
                _sync_file(destination.fileno())

        if temporary.stat().st_size != original_size:
            raise OSError("File size verification failed before publication")
        # Exclusive normal-file creation works without hard-link support and
        # cannot overwrite an output that appeared after initial validation.
        _publish_file(temporary, output_path)
        published = True
        output_size = output_path.stat().st_size
        if output_size != original_size:
            raise OSError("Output file size differs from the original")
        logger.info(
            "Processing completed successfully: replacements=%d final_size=%d",
            count, output_size,
        )
        return count
    except Exception:
        logger.exception("Binary ID processing failed")
        if published:
            try:
                output_path.unlink()
            except OSError:
                logger.exception(
                    "Could not remove invalid output: %s", output_path
                )
        raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Could not remove temporary file: %s", temporary
                )
