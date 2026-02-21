# asus-ite5570-rgb

Linux daemon for controlling RGB lighting on ASUS laptops with the ITE5570 
embedded controller (VID `0x0B05`, PID `0x5570`) via I2C HID LampArray standard.

> ⚠️ **Vibecoded for my own machine.**
> This was built and tested on a single ASUS Vivobook model.
> The ITE5570 chip exists across multiple ASUS product lines but firmware
> behavior, lamp count, and report layout may differ between models.
> It may work on yours, it may not — no guarantees.

## What it does
- Takes lighting control from the ASUS firmware via HID LampArray (reports `0x41`–`0x46`)
- Runs as a systemd service on Fedora Linux
- Reacts to config changes without restarting — edit `config.json`, run `systemctl reload`
- Supports static color, breathing effect, and firmware passthrough (off)
- Zero dependencies — stdlib only (`fcntl`, `ctypes`, `struct`)

## Configuration

Config file location: `/etc/ite5570/config.json`

Apply changes without restarting the service:
```bash
systemctl reload ite5570
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `static` | Lighting mode — see below |
| `color` | `[R, G, B]` | `[255, 0, 0]` | RGB color, each value 0–255 |
| `intensity` | int | `255` | Master brightness multiplier 0–255 |
| `breathe_step_ms` | int | `20` | Milliseconds between brightness steps in breathe mode |

### Modes

| Mode | Description |
|------|-------------|
| `static` | Solid color, set once and held |
| `breathe` | Continuously ramps brightness 0→255→0 in the set color |
| `off` | Turns all lamps off and releases control back to firmware |

### Examples

Solid blue at half brightness:
```json
{
    "mode": "static",
    "color": [0, 0, 255],
    "intensity": 128
}
```

Slow green breathe:
```json
{
    "mode": "breathe",
    "color": [0, 255, 0],
    "intensity": 255,
    "breathe_step_ms": 50
}
```

Off — hand control back to ASUS firmware:
```json
{
    "mode": "off"
}
```

## Tested on
| Model | Kernel | Status |
|-------|--------|--------|
| ASUS Vivobook S 16 OLED M5606UA-MX026 | 6.18.12-200.fc43.x86_64 | ✅ working |

If it works on your machine, open a PR and add your model to the table.