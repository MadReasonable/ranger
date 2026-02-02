# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.
# Author: Lloyd Park, 2026

"""Interface for XTWINOPS terminal sequences."""

from __future__ import (absolute_import, division, print_function)

from fcntl import fcntl
import os
import re
import select
import struct
import sys
import termios
import time
import tty


TMUX_START = b'\x1bPtmux;\x1b'
TMUX_END = b'\x1b\\'

DEVICE_ATTRIBUTES_2_Q = '\x1b[>0c'
DEVICE_ATTRIBUTES_2_RE = re.compile(rb'\x1b\[>([^c]*)c')

XTWINOPS_CELL_SIZE_Q = '\x1b[16t'
XTWINOPS_CELL_SIZE_RE = re.compile(rb'\x1b\[6;(\d+);(\d+)t')


def terminal_is_tmux():
    return os.environ.get("TMUX")


def tmux_wrap_sequence(sequence):
    return TMUX_START + sequence + TMUX_END


_terminal_is_windows_terminal = None  # pylint: disable=invalid-name


def terminal_is_windows_terminal():
    global _terminal_is_windows_terminal  # pylint: disable=global-statement
    if _terminal_is_windows_terminal is not None:
        return _terminal_is_windows_terminal

    query = DEVICE_ATTRIBUTES_2_Q
    if terminal_is_tmux():
        query = tmux_wrap_sequence(query)

    match = csi_query(query, DEVICE_ATTRIBUTES_2_RE)
    if match and match.group(0) == b'0;10;1':
        _terminal_is_windows_terminal = True

    return _terminal_is_windows_terminal is True


def get_terminal_size():
    farg = struct.pack("HHHH", 0, 0, 0, 0)
    fd_stdout = sys.stdout.fileno()
    fretint = fcntl.ioctl(fd_stdout, termios.TIOCGWINSZ, farg)
    return struct.unpack("HHHH", fretint)


_terminal_rows, _terminal_cols = 0, 0  # pylint: disable=invalid-name
_xtwinops_cell_size = None             # pylint: disable=invalid-name


def get_font_dimensions():
    """
    Get the height and width of a character displayed in the terminal in
    pixels.
    """
    rows, cols, xpixels, ypixels = get_terminal_size()
    if xpixels > 0 or ypixels > 0:
        return (xpixels // cols), (ypixels // rows)

    global _terminal_rows, _terminal_cols  # pylint: disable=global-statement,invalid-name
    global _xtwinops_cell_size             # pylint: disable=global-statement,invalid-name

    if _terminal_rows != rows or _terminal_cols != cols:
        _terminal_rows, _terminal_cols = rows, cols
        match = csi_query(XTWINOPS_CELL_SIZE_Q, XTWINOPS_CELL_SIZE_RE)
        if match:
            _xtwinops_cell_size = (int(match.group(2)), int(match.group(1)))
    if _xtwinops_cell_size is not None:
        return _xtwinops_cell_size

    return 5, 7  # conservative defaults


def csi_query(query, response_pattern, timeout=0.05):
    """
    Generic function to send XTWINOPS query and wait for response.
    """
    # Normalize pattern
    if hasattr(response_pattern, "search"):
        def matcher(buf):
            return response_pattern.search(buf)
    else:
        if isinstance(response_pattern, str):
            response_pattern = response_pattern.encode("ascii")

        def matcher(buf):
            return buf.find(response_pattern)

    # Save terminal state
    stdin = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(stdin)
    try:
        tty.setcbreak(stdin)

        # Send query
        sys.stdout.write(query)
        sys.stdout.flush()

        response = bytearray()
        end_time = time.monotonic() + timeout
        while True:
            remaining = end_time - time.monotonic()
            if remaining <= 0:
                return None

            ready, _, _ = select.select([stdin], [], [], remaining)
            if ready:
                response.extend(os.read(stdin, 64))
                match = matcher(response)
                if match:
                    return match

            if len(response) > 256:
                return None

    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, old_attrs)

