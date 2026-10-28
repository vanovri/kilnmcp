"""UART replay: NMEA-like frames as a raw byte stream (file or serial port). No hardware needed.

Frame: $KILN,<batch_id>,<ts>,<sensor>,<value>*<XOR-checksum hex>\\r\\n
"""
from __future__ import annotations
import argparse, io
from typing import Iterable, Iterator
from . import db
from .simulator import SimConfig, simulate, ingest, parse_fault

def _chk(body: str) -> str:
    c = 0
    for b in body.encode():
        c ^= b
    return f"{c:02X}"

def encode(batch_id: str, ts: float, sensor: str, value: float) -> bytes:
    body = f"KILN,{batch_id},{ts:.0f},{sensor},{value}"
    return f"${body}*{_chk(body)}\r\n".encode()

def write_frames(cfg: SimConfig, path: str) -> int:
    n = 0
    with open(path, "wb") as f:
        for ts, s, v in simulate(cfg):
            f.write(encode(cfg.batch_id, ts, s, v)); n += 1
    return n

def parse_stream(chunks: Iterable[bytes], stats: dict | None = None) -> Iterator[tuple]:
    """Reassemble frames from arbitrary byte chunks; drop bad checksums / garbage."""
    stats = stats if stats is not None else {}
    stats.setdefault("ok", 0); stats.setdefault("bad", 0)
    buf = b""
    for chunk in chunks:
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            i = line.find(b"$")
            if i < 0 or b"*" not in line:
                if line: stats["bad"] += 1
                continue
            try:
                body, chk = line[i + 1:].decode("ascii").rsplit("*", 1)
                if _chk(body) != chk.upper():
                    stats["bad"] += 1; continue
                tag, batch, ts, sensor, val = body.split(",")
                assert tag == "KILN"
                stats["ok"] += 1
                yield batch, float(ts), sensor, float(val)
            except Exception:
                stats["bad"] += 1

def file_chunks(path: str, size: int = 64) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while b := f.read(size):
            yield b

def serial_chunks(port: str, baud: int = 115200, idle_timeout: float = 2.0) -> Iterator[bytes]:
    import serial  # pyserial; e.g. a socat pty or STM32 VCP
    with serial.Serial(port, baud, timeout=idle_timeout) as s:
        while b := s.read(256):
            yield b

def replay(con, chunks: Iterable[bytes]) -> dict:
    stats: dict = {}
    rows = [(b, ts, s, v, "uart") for b, ts, s, v in parse_stream(chunks, stats)]
    con.executemany("INSERT INTO readings(batch_id,ts,sensor,value,source) VALUES(?,?,?,?,?)", rows)
    con.commit()
    return stats

def main(argv=None):
    ap = argparse.ArgumentParser(description="KilnMCP UART frames (SYNTHETIC)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write"); w.add_argument("out"); w.add_argument("--batch", default="SYN-UART-1")
    w.add_argument("--seed", type=int, default=7); w.add_argument("--fault", action="append", default=[])
    r = sub.add_parser("replay"); r.add_argument("--file"); r.add_argument("--port")
    r.add_argument("--batch", default="SYN-UART-1"); r.add_argument("--seed", type=int, default=7)
    r.add_argument("--fault", action="append", default=[])
    a = ap.parse_args(argv)
    cfg = SimConfig(batch_id=a.batch, seed=a.seed, faults=[parse_fault(f) for f in a.fault])
    if a.cmd == "write":
        print(f"wrote {write_frames(cfg, a.out)} SYNTHETIC frames -> {a.out}")
    else:
        con = db.connect()
        ingest(con, cfg, source="uart")  # batch metadata only
        chunks = serial_chunks(a.port) if a.port else file_chunks(a.file)
        print("replay stats:", replay(con, chunks))

if __name__ == "__main__":
    main()
