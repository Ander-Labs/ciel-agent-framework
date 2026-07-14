from __future__ import annotations

import gzip
import zlib
from dataclasses import dataclass
from typing import Any


@dataclass
class CompressionRecord:
    original: bytes
    payload: bytes
    algorithm: str
    original_size: int
    compressed_size: int


def gzip_compress(data: bytes, level: int = 6) -> CompressionRecord:
    payload = gzip.compress(data, compresslevel=level)
    return CompressionRecord(
        original=data,
        payload=payload,
        algorithm="gzip",
        original_size=len(data),
        compressed_size=len(payload),
    )


def gzip_decompress(record: CompressionRecord) -> bytes:
    if record.algorithm != "gzip":
        raise ValueError(f"unsupported algorithm: {record.algorithm}")
    return gzip.decompress(record.payload)


def zlib_compress(data: bytes, level: int = 6) -> CompressionRecord:
    payload = zlib.compress(data, level=level)
    return CompressionRecord(
        original=data,
        payload=payload,
        algorithm="zlib",
        original_size=len(data),
        compressed_size=len(payload),
    )


def zlib_decompress(record: CompressionRecord) -> bytes:
    if record.algorithm != "zlib":
        raise ValueError(f"unsupported algorithm: {record.algorithm}")
    return zlib.decompress(record.payload)


def compress_factory(data: bytes, *, algorithm: str = "gzip", level: int = 6) -> CompressionRecord:
    if algorithm == "gzip":
        return gzip_compress(data, level=level)
    if algorithm == "zlib":
        return zlib_compress(data, level=level)
    raise ValueError(f"unsupported algorithm: {algorithm}")
