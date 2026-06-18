# Board configuration

Board profiles for the flasher live here. Each `board-config.json` describes which
PlatformIO board to build, which verification probes to run, and the board-specific
`sensor`/battery/LED values injected at build time.

| File | Purpose |
|------|---------|
| `board-config.json` | Default profile (NodeMCU + LSM6DSV smoke test) |
| `board-config.schema.json` | JSON Schema for flashing-tool configs |
| `board-defaults.schema.json` | Shared SlimeVR board-values schema (from firmware repo) |

Run the flasher with a specific profile:

```bash
python -m flasher --config config/board-config.json
```

Add new profiles by copying `board-config.json` and adjusting `type`, `tests`, and
`defaults` for your board.
