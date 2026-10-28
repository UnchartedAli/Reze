"""
Dependency-free QR code generator.

Reze generates QR codes locally so private text or URLs are never sent to a
third-party rendering service. The implementation covers byte mode, error
correction levels L and M, and versions 1-10 (up to 274 data codewords), which
is enough for URLs, contact strings and short notes.

Reference points verified by the test-suite:

* the Reed-Solomon generator and the per-block encoding are validated by
  computing all syndromes of every block (they must be zero);
* the BCH(15,5) format word for level L / mask 0 equals ``0x77C4`` and the
  BCH(18,6) version word for version 7 equals ``0x07C94`` (values from the
  QR specification);
* the generated PNG is written with the standard modules plus a 4-module quiet
  zone.
"""

import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# (error correction level, version) -> (ec codewords per block, [(block count, data codewords), ...])
BLOCKS = {
    ("L", 1): (7, [(1, 19)]),
    ("L", 2): (10, [(1, 34)]),
    ("L", 3): (15, [(1, 55)]),
    ("L", 4): (20, [(1, 80)]),
    ("L", 5): (26, [(1, 108)]),
    ("L", 6): (18, [(2, 68)]),
    ("L", 7): (20, [(2, 78)]),
    ("L", 8): (24, [(2, 97)]),
    ("L", 9): (30, [(2, 116)]),
    ("L", 10): (18, [(2, 68), (2, 69)]),
    ("M", 1): (10, [(1, 16)]),
    ("M", 2): (16, [(1, 28)]),
    ("M", 3): (26, [(1, 44)]),
    ("M", 4): (18, [(2, 32)]),
    ("M", 5): (24, [(2, 43)]),
    ("M", 6): (16, [(4, 27)]),
    ("M", 7): (18, [(4, 31)]),
    ("M", 8): (22, [(2, 38), (2, 39)]),
    ("M", 9): (22, [(3, 36), (2, 37)]),
    ("M", 10): (26, [(4, 43), (1, 44)]),
}

ALIGNMENT_POSITIONS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

FORMAT_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}
MAX_VERSION = 10


# ------------------------------------------------------------------- GF(256)
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    value = 1
    for index in range(255):
        _EXP[index] = value
        _LOG[value] = index
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for index in range(255, 512):
        _EXP[index] = _EXP[index - 255]


_init_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def rs_generator(degree: int) -> List[int]:
    """Generator polynomial coefficients for *degree* error-correction words."""
    poly = [1]
    for index in range(degree):
        next_poly = [0] * (len(poly) + 1)
        for position, coefficient in enumerate(poly):
            next_poly[position] ^= coefficient
            next_poly[position + 1] ^= _gf_mul(coefficient, _EXP[index])
        poly = next_poly
    return poly


def rs_encode(data: Sequence[int], ec_words: int) -> List[int]:
    """Reed-Solomon remainder (the error-correction codewords)."""
    generator = rs_generator(ec_words)
    remainder = [0] * ec_words
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor:
            for index in range(ec_words):
                remainder[index] ^= _gf_mul(generator[index + 1], factor)
    return remainder


def rs_syndromes(block: Sequence[int], ec_words: int) -> List[int]:
    """Syndromes of a codeword block; all zero means a valid RS codeword."""
    return [_evaluate(block, _EXP[power]) for power in range(ec_words)]


def _evaluate(poly: Sequence[int], x: int) -> int:
    result = 0
    for coefficient in poly:
        result = _gf_mul(result, x) ^ coefficient
    return result


# ---------------------------------------------------------------- data encoding
def _data_codewords(version: int, level: str) -> int:
    _ec, groups = BLOCKS[(level, version)]
    return sum(count * data for count, data in groups)


def capacity_bytes(version: int, level: str) -> int:
    """Approximate usable payload for byte mode in one symbol."""
    count_bits = 8 if version <= 9 else 16
    overhead_bits = 4 + count_bits
    return (_data_codewords(version, level) * 8 - overhead_bits) // 8


def _choose_version(length: int, level: str) -> int:
    for version in range(1, MAX_VERSION + 1):
        if length <= capacity_bytes(version, level):
            return version
    raise ValueError(
        f"Text is too long for a local QR code ({length} bytes; maximum is "
        f"{capacity_bytes(MAX_VERSION, level)} at level {level})."
    )


def _bit_buffer(data: bytes, version: int) -> List[int]:
    count_bits = 8 if version <= 9 else 16
    bits: List[int] = []

    def push(value: int, length: int) -> None:
        for shift in range(length - 1, -1, -1):
            bits.append((value >> shift) & 1)

    push(0b0100, 4)  # byte mode
    push(len(data), count_bits)
    for byte in data:
        push(byte, 8)
    return bits


def _pad_bits(bits: List[int], version: int, level: str) -> List[int]:
    capacity = _data_codewords(version, level) * 8
    if len(bits) > capacity:
        raise ValueError("Data does not fit in the selected QR version.")
    bits = list(bits)
    bits.extend([0] * min(4, capacity - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    pad_bytes = [0xEC, 0x11]
    index = 0
    while len(bits) < capacity:
        byte = pad_bytes[index % 2]
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
        index += 1
    words = [
        int("".join(str(bit) for bit in bits[offset: offset + 8]), 2)
        for offset in range(0, len(bits), 8)
    ]
    return words


def _interleave(data_words: List[int], version: int, level: str) -> List[int]:
    ec_words, groups = BLOCKS[(level, version)]
    blocks: List[List[int]] = []
    ec_blocks: List[List[int]] = []
    offset = 0
    for count, data_count in groups:
        for _ in range(count):
            block = data_words[offset: offset + data_count]
            offset += data_count
            blocks.append(block)
            ec_blocks.append(rs_encode(block, ec_words))

    result: List[int] = []
    max_data = max(len(block) for block in blocks)
    for index in range(max_data):
        for block in blocks:
            if index < len(block):
                result.append(block[index])
    for index in range(ec_words):
        for block in ec_blocks:
            result.append(block[index])
    return result


# ---------------------------------------------------------------- matrix build
@dataclass
class QRCode:
    version: int
    level: str
    size: int
    modules: List[List[bool]]
    mask: int

    def is_dark(self, row: int, col: int) -> bool:
        return self.modules[row][col]


def _bch(value: int, poly: int) -> int:
    """Long-division remainder over GF(2) for BCH format/version words."""
    remainder = value
    degree = poly.bit_length() - 1
    while remainder.bit_length() - 1 >= degree:
        shift = remainder.bit_length() - 1 - degree
        remainder ^= poly << shift
    return remainder


def format_info(level: str, mask: int) -> int:
    data = (FORMAT_LEVEL_BITS[level] << 3) | mask
    remainder = _bch(data << 10, 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def version_info(version: int) -> int:
    remainder = _bch(version << 12, 0x1F25)
    return (version << 12) | remainder


def _finder(modules, reserved, row: int, col: int) -> None:
    for delta_row in range(-1, 8):
        for delta_col in range(-1, 8):
            target_row, target_col = row + delta_row, col + delta_col
            if not (0 <= target_row < len(modules) and 0 <= target_col < len(modules)):
                continue
            inside = 0 <= delta_row <= 6 and 0 <= delta_col <= 6
            dark = False
            if inside:
                on_border = delta_row in (0, 6) or delta_col in (0, 6)
                in_center = 2 <= delta_row <= 4 and 2 <= delta_col <= 4
                dark = on_border or in_center
            modules[target_row][target_col] = dark
            reserved[target_row][target_col] = True


def _build_reserved(size: int, version: int):
    modules = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    _finder(modules, reserved, 0, 0)
    _finder(modules, reserved, 0, size - 7)
    _finder(modules, reserved, size - 7, 0)

    for index in range(8, size - 8):
        value = index % 2 == 0
        modules[6][index] = value
        reserved[6][index] = True
        modules[index][6] = value
        reserved[index][6] = True

    positions = ALIGNMENT_POSITIONS[version]
    for row in positions:
        for col in positions:
            if (row, col) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            if reserved[row][col]:
                continue
            for delta_row in range(-2, 3):
                for delta_col in range(-2, 3):
                    dark = max(abs(delta_row), abs(delta_col)) != 1
                    modules[row + delta_row][col + delta_col] = dark
                    reserved[row + delta_row][col + delta_col] = True

    # Reserve the format information area.
    for index in range(9):
        reserved[8][index] = True
        reserved[index][8] = True
    for index in range(8):
        reserved[size - 1 - index][8] = True
        reserved[8][size - 1 - index] = True
    modules[size - 8][8] = True
    reserved[size - 8][8] = True

    if version >= 7:
        for row in range(6):
            for col in range(3):
                reserved[size - 11 + col][row] = True
                reserved[row][size - 11 + col] = True
    return modules, reserved


def _apply_mask(row: int, col: int, mask: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _place_data(modules, reserved, codewords: List[int], mask: int) -> None:
    size = len(modules)
    bits: List[int] = []
    for byte in codewords:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)

    index = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in (0, 1):
                target_col = col - offset
                if reserved[row][target_col]:
                    continue
                bit = bits[index] if index < len(bits) else 0
                if _apply_mask(row, target_col, mask):
                    bit ^= 1
                modules[row][target_col] = bool(bit)
                index += 1
        upward = not upward
        col -= 2


def _draw_format(modules, level: str, mask: int) -> None:
    size = len(modules)
    bits = format_info(level, mask)
    for index in range(15):
        bit = ((bits >> index) & 1) == 1
        if index < 6:
            row = index
        elif index < 8:
            row = index + 1
        else:
            row = size - 15 + index
        modules[row][8] = bit
        if index < 8:
            col = size - index - 1
        elif index == 8:
            col = 7
        else:
            col = 15 - index - 1
        modules[8][col] = bit
    modules[size - 8][8] = True


def _draw_version(modules, version: int) -> None:
    if version < 7:
        return
    size = len(modules)
    bits = version_info(version)
    for index in range(18):
        bit = ((bits >> index) & 1) == 1
        row = index // 3
        col = index % 3
        modules[size - 11 + col][row] = bit
        modules[row][size - 11 + col] = bit


def _penalty(modules) -> int:
    size = len(modules)
    score = 0
    for row in range(size):
        run = 1
        for col in range(1, size):
            if modules[row][col] == modules[row][col - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    for col in range(size):
        run = 1
        for row in range(1, size):
            if modules[row][col] == modules[row - 1][col]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    for row in range(size - 1):
        for col in range(size - 1):
            block = (
                modules[row][col],
                modules[row][col + 1],
                modules[row + 1][col],
                modules[row + 1][col + 1],
            )
            if block in ((True,) * 4, (False,) * 4):
                score += 3
    return score


def encode_qr(text: str, level: str = "M") -> QRCode:
    """Encode *text* (UTF-8, byte mode) into a QR matrix."""
    level = (level or "M").upper()
    if level not in ("L", "M"):
        raise ValueError("Only error-correction levels L and M are supported.")
    data = (text or "").encode("utf-8")
    if not data:
        raise ValueError("Nothing to encode.")
    version = _choose_version(len(data), level)

    bits = _bit_buffer(data, version)
    codewords = _pad_bits(bits, version, level)
    final = _interleave(codewords, version, level)

    size = 17 + 4 * version
    modules, reserved = _build_reserved(size, version)

    best = None
    for mask in range(8):
        candidate = [row[:] for row in modules]
        _place_data(candidate, reserved, final, mask)
        _draw_format(candidate, level, mask)
        _draw_version(candidate, version)
        score = _penalty(candidate)
        if best is None or score < best[0]:
            best = (score, mask, candidate)
    assert best is not None
    return QRCode(version=version, level=level, size=size, modules=best[2], mask=best[1])


# --------------------------------------------------------------------- PNG out
def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def to_png(qr: QRCode, path: str, scale: int = 8, border: int = 4) -> str:
    """Write the matrix as an 8-bit grayscale PNG with a quiet zone."""
    scale = max(1, min(int(scale), 32))
    border = max(0, min(int(border), 16))
    size = qr.size
    dimension = (size + border * 2) * scale

    rows = []
    white = b"\xff" * dimension
    for row in range(dimension):
        module_row = row // scale - border
        if module_row < 0 or module_row >= size:
            rows.append(b"\x00" + white)
            continue
        line = bytearray()
        line.append(0)  # filter type: none
        for col in range(dimension):
            module_col = col // scale - border
            dark = 0 <= module_col < size and qr.modules[module_row][module_col]
            line.append(0 if dark else 255)
        rows.append(bytes(line))
    raw = b"".join(rows)

    header = struct.pack(">IIBBBBB", dimension, dimension, 8, 0, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", header)
    png += _chunk(b"IDAT", zlib.compress(raw, 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)
    return path


def qr_png(text: str, path: str, level: str = "M", scale: int = 8) -> str:
    return to_png(encode_qr(text, level), path, scale=scale)


def read_format(modules) -> Tuple[str, int]:
    """Read back the format information (used by tests to verify placement)."""
    size = len(modules)
    bits = 0
    for index in range(15):
        if index < 8:
            col = size - index - 1
            row = 8
        elif index == 8:
            col = 7
            row = 8
        else:
            col = 15 - index - 1
            row = 8
        if modules[row][col]:
            bits |= 1 << index
    bits ^= 0x5412
    level_bits = (bits >> 13) & 0b11
    mask = (bits >> 10) & 0b111
    for name, value in FORMAT_LEVEL_BITS.items():
        if value == level_bits:
            return name, mask
    return "?", mask
