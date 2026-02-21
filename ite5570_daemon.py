"""
ite5570_daemon.py
=================
Systemd daemon — runs continuously, watches /etc/ite5570/config.json for changes
and applies new lighting settings without restarting the service.

Signals:
  SIGHUP  → reload config immediately (same as editing the file)
  SIGTERM → release LEDs to firmware and exit cleanly

Config file: /etc/ite5570/config.json
Logs:        journalctl -u ite5570 -f
"""

import os
import sys
import json
import struct
import fcntl
import glob
import time
import signal
import logging
from dataclasses import dataclass, field
from typing import Optional

# ── Logging ────────────────────────────────────────────────────────────────────
# When running under systemd, stdout/stderr go to journald automatically.
# No need for a separate log file.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ite5570")

# ── Config ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = "/etc/ite5570/config.json"

@dataclass
class Config:
    mode:           str        = "static"   # static | breathe | off
    color:          list       = field(default_factory=lambda: [255, 0, 0])
    intensity:      int        = 255
    breathe_step_ms: int       = 20

    @property
    def r(self): return int(self.color[0])
    @property
    def g(self): return int(self.color[1])
    @property
    def b(self): return int(self.color[2])

def load_config(path: str = CONFIG_PATH) -> Config:
    """
    Parse config JSON.
    Comments in JSON (lines starting with //) are stripped before parsing
    so the config file can have human-readable annotations.
    """
    try:
        with open(path) as f:
            raw = f.read()
        # Strip // comment lines — not valid JSON but useful for humans
        lines   = [l for l in raw.splitlines() if not l.strip().startswith("//")]
        data    = json.loads("\n".join(lines))
        cfg     = Config(
            mode            = data.get("mode", "static"),
            color           = data.get("color", [255, 0, 0]),
            intensity       = int(data.get("intensity", 255)),
            breathe_step_ms = int(data.get("breathe_step_ms", 20)),
        )
        log.info(f"Config loaded: mode={cfg.mode}  RGB({cfg.r},{cfg.g},{cfg.b})  intensity={cfg.intensity}")
        return cfg
    except Exception as e:
        log.error(f"Failed to load config: {e} — keeping previous config")
        return None

def config_mtime(path: str = CONFIG_PATH) -> float:
    """Return config file modification timestamp — used to detect changes."""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0

# ── ioctl numbers ──────────────────────────────────────────────────────────────

def _HIDIOCSFEATURE(size): return (3 << 30) | (size << 16) | (0x48 << 8) | 0x06
def _HIDIOCGFEATURE(size): return (3 << 30) | (size << 16) | (0x48 << 8) | 0x07
def _HIDIOCGRAWINFO():     return (2 << 30) | (8  << 16) | (0x48 << 8) | 0x03

TARGET_VID = 0x0B05
TARGET_PID = 0x5570

# ── Device discovery ───────────────────────────────────────────────────────────

def find_hidraw(vid: int, pid: int) -> Optional[str]:
    for path in sorted(glob.glob("/dev/hidraw*")):
        try:
            fd  = os.open(path, os.O_RDWR)
            buf = bytearray(8)
            fcntl.ioctl(fd, _HIDIOCGRAWINFO(), buf)
            _, device_vid, device_pid = struct.unpack_from("<IHH", buf)
            os.close(fd)
            if device_vid == vid and device_pid == pid:
                return path
        except (PermissionError, OSError):
            pass
    return None

# ── Feature report I/O ─────────────────────────────────────────────────────────

def set_feature(fd: int, data: bytes):
    buf = bytearray(data)
    fcntl.ioctl(fd, _HIDIOCSFEATURE(len(buf)), buf)

def get_feature(fd: int, report_id: int, length: int) -> bytes:
    buf    = bytearray(length)
    buf[0] = report_id
    fcntl.ioctl(fd, _HIDIOCGFEATURE(length), buf)
    return bytes(buf)

# ── Report builders ────────────────────────────────────────────────────────────

def report_control(autonomous: bool) -> bytes:
    return struct.pack("<BB", 0x46, 0x01 if autonomous else 0x00)

def report_range(start, end, r, g, b, intensity=255, apply_now=True) -> bytes:
    return struct.pack("<BBHHBBBB", 0x45, 0x01 if apply_now else 0x00,
                       start, end, r, g, b, intensity)

# ── Lamp count ─────────────────────────────────────────────────────────────────

def read_lamp_count(fd: int) -> int:
    try:
        raw   = get_feature(fd, 0x41, 23)
        count = struct.unpack_from("<H", raw, 1)[0]
        log.info(f"LampCount from device: {count}")
        return count
    except OSError:
        log.warning("Could not read LampArray attributes — defaulting to 128")
        return 128

# ── Device class ───────────────────────────────────────────────────────────────

class ITE5570:
    def __init__(self):
        self.fd         = None
        self.lamp_count = 128
        self._connect()

    def _connect(self):
        """Find and open the hidraw node. Retries until device appears."""
        while True:
            path = find_hidraw(TARGET_VID, TARGET_PID)
            if path:
                try:
                    self.fd         = os.open(path, os.O_RDWR)
                    self.lamp_count = read_lamp_count(self.fd)
                    set_feature(self.fd, report_control(autonomous=False))
                    log.info(f"Device opened: {path}  fd={self.fd}  lamps={self.lamp_count}")
                    return
                except OSError as e:
                    log.error(f"Failed to open {path}: {e}")
            log.warning("Device not found — retrying in 5 s")
            time.sleep(5)

    def _ensure_connected(self):
        """Reconnect if the fd went stale (e.g. device re-enumerated after suspend)."""
        if self.fd is None:
            self._connect()
        else:
            try:
                # Cheap probe: try reading attributes
                get_feature(self.fd, 0x41, 23)
            except OSError:
                log.warning("Device lost — reconnecting")
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = None
                self._connect()

    def fill(self, r: int, g: int, b: int, intensity: int = 255):
        self._ensure_connected()
        set_feature(self.fd, report_range(0, self.lamp_count - 1, r, g, b, intensity))

    def off(self):
        self.fill(0, 0, 0, 0)
        set_feature(self.fd, report_control(autonomous=True))
        log.info("LEDs released to firmware")

    def close(self):
        if self.fd is not None:
            try:
                set_feature(self.fd, report_control(autonomous=True))
                os.close(self.fd)
                log.info("Device closed — firmware control restored")
            except OSError:
                pass
            self.fd = None

# ── Daemon loop ────────────────────────────────────────────────────────────────

class Daemon:
    def __init__(self):
        self.dev          = ITE5570()
        self.cfg          = load_config() or Config()
        self._last_mtime  = config_mtime()
        self._reload_flag = False   # set by SIGHUP handler
        self._stop_flag   = False   # set by SIGTERM handler
        self._breathe_pos = 0       # current position in breathe ramp

        signal.signal(signal.SIGHUP,  self._on_sighup)
        signal.signal(signal.SIGTERM, self._on_sigterm)
        signal.signal(signal.SIGINT,  self._on_sigterm)

        log.info("Daemon started")

    def _on_sighup(self, *_):
        """SIGHUP = reload config. Safe to set flag from signal context."""
        log.info("SIGHUP received — reloading config")
        self._reload_flag = True

    def _on_sigterm(self, *_):
        log.info("SIGTERM received — shutting down")
        self._stop_flag = True

    def _check_config_changed(self):
        """Poll config file mtime — if changed, reload."""
        mtime = config_mtime()
        if mtime != self._last_mtime:
            log.info("Config file changed — reloading")
            self._last_mtime  = mtime
            self._reload_flag = True

    def _reload_if_needed(self):
        if self._reload_flag:
            new_cfg = load_config()
            if new_cfg:
                self.cfg          = new_cfg
                self._breathe_pos = 0   # restart breathe ramp on mode change
            self._reload_flag = False

    def _apply_static(self):
        self.dev.fill(self.cfg.r, self.cfg.g, self.cfg.b, self.cfg.intensity)

    def _step_breathe(self):
        """
        Advance one step of the breathing ramp.
        Ramp: 0 → 255 → 0, one step per call.
        The main loop calls this every breathe_step_ms milliseconds.
        """
        ramp = list(range(0, 256, 5)) + list(range(255, -1, -5))
        self._breathe_pos = self._breathe_pos % len(ramp)
        intensity         = ramp[self._breathe_pos]
        self._breathe_pos += 1
        self.dev.fill(
            int(self.cfg.r * intensity / 255),
            int(self.cfg.g * intensity / 255),
            int(self.cfg.b * intensity / 255),
            intensity,
        )

    def run(self):
        # Apply initial config before entering loop
        self._apply_mode()

        while not self._stop_flag:
            self._check_config_changed()
            self._reload_if_needed()

            if self.cfg.mode == "breathe":
                self._step_breathe()
                time.sleep(self.cfg.breathe_step_ms / 1000)
            else:
                # static / off — no need to hammer the device; just check config periodically
                self._apply_mode()
                time.sleep(1)

        # Shutdown
        self.dev.close()
        log.info("Daemon stopped")

    def _apply_mode(self):
        if self.cfg.mode == "static":
            self._apply_static()
        elif self.cfg.mode == "breathe":
            self._step_breathe()
        elif self.cfg.mode == "off":
            self.dev.off()
        else:
            log.warning(f"Unknown mode '{self.cfg.mode}' — defaulting to static")
            self._apply_static()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    Daemon().run()
