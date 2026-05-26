"""
Lightweight RTT (Real-Time Transfer) helper.

Generates a minimal SEGGER_RTT.c/.h pair you can drop into a project's
Drive/ folder so printf-style logs go through SWD instead of USART.
This avoids burning a UART when one is unavailable.

Also bridges to a host-side viewer command (J-Link RTT Viewer or
JLinkRTTLogger) for convenience.

Usage (from skill):
    python rtt_helper.py --emit <project_dir>           # drop SEGGER_RTT files
    python rtt_helper.py --view --chip STM32F407ZGT6    # launch JLinkRTTLogger
"""
import os
import sys
import shutil
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import find_jlink_exe, run_command, load_chip_db


_RTT_H = '''#ifndef SEGGER_RTT_H
#define SEGGER_RTT_H

/* Tiny wrapper around the SEGGER RTT public API. Drop the official
 * SEGGER_RTT_V*.zip into Drive/RTT/ if you need the full feature set;
 * for printf-only logging this minimal subset is enough. */

#include <stdarg.h>

int  SEGGER_RTT_Init(void);
int  SEGGER_RTT_printf(unsigned BufferIndex, const char *sFormat, ...);
int  SEGGER_RTT_WriteString(unsigned BufferIndex, const char *s);
int  SEGGER_RTT_HasKey(void);
int  SEGGER_RTT_GetKey(void);

#endif
'''

_RTT_C = '''/* Minimal RTT control block — compatible with J-Link RTT Viewer.
 *
 * For full RTT features (ring buffer mgmt, multi-channel) replace this
 * file with the official SEGGER_RTT.c from
 * https://www.segger.com/downloads/jlink/SEGGER_RTT.zip
 */
#include "SEGGER_RTT.h"
#include <stdio.h>
#include <string.h>

#define BUFFER_SIZE_UP   1024
#define BUFFER_SIZE_DOWN  16

static char _UpBuf[BUFFER_SIZE_UP];
static char _DownBuf[BUFFER_SIZE_DOWN];

typedef struct {
    const char *sName;
    char       *pBuffer;
    unsigned    SizeOfBuffer;
    unsigned    WrOff;
    unsigned    RdOff;
    unsigned    Flags;
} RTT_BUFFER;

typedef struct {
    char       acID[16];
    int        MaxNumUpBuffers;
    int        MaxNumDownBuffers;
    RTT_BUFFER aUp[1];
    RTT_BUFFER aDown[1];
} SEGGER_RTT_CB;

/* "SEGGER RTT" magic — viewer scans RAM for this exact string. */
SEGGER_RTT_CB _SEGGER_RTT __attribute__((used)) = {
    {'S','E','G','G','E','R',' ','R','T','T','\\0'},
    1, 1,
    {{ "Terminal", _UpBuf,   BUFFER_SIZE_UP,   0, 0, 0 }},
    {{ "Terminal", _DownBuf, BUFFER_SIZE_DOWN, 0, 0, 0 }},
};

int SEGGER_RTT_Init(void) { return 0; }

int SEGGER_RTT_WriteString(unsigned ch, const char *s)
{
    (void)ch;
    RTT_BUFFER *b = &_SEGGER_RTT.aUp[0];
    unsigned n = (unsigned)strlen(s);
    for (unsigned i = 0; i < n; i++) {
        unsigned next = (b->WrOff + 1) % b->SizeOfBuffer;
        while (next == b->RdOff) { /* viewer-not-attached: spin briefly */
            return (int)i;
        }
        b->pBuffer[b->WrOff] = s[i];
        b->WrOff = next;
    }
    return (int)n;
}

int SEGGER_RTT_printf(unsigned ch, const char *sFormat, ...)
{
    char tmp[160];
    va_list ap;
    va_start(ap, sFormat);
    int n = vsnprintf(tmp, sizeof(tmp), sFormat, ap);
    va_end(ap);
    if (n > 0) SEGGER_RTT_WriteString(ch, tmp);
    return n;
}

int SEGGER_RTT_HasKey(void)
{
    RTT_BUFFER *b = &_SEGGER_RTT.aDown[0];
    return b->WrOff != b->RdOff;
}

int SEGGER_RTT_GetKey(void)
{
    RTT_BUFFER *b = &_SEGGER_RTT.aDown[0];
    if (b->WrOff == b->RdOff) return -1;
    int c = (unsigned char)b->pBuffer[b->RdOff];
    b->RdOff = (b->RdOff + 1) % b->SizeOfBuffer;
    return c;
}
'''

_README = '''# RTT (Real-Time Transfer)

This project ships with a minimal SEGGER_RTT control block. Use it instead
of (or alongside) USART for `printf`-style logs:

```c
#include "SEGGER_RTT.h"

int main(void) {
    SEGGER_RTT_Init();
    SEGGER_RTT_printf(0, "boot @ %u\\n", HAL_GetTick());
    while (1) { ... }
}
```

## Viewing logs (host)

J-Link required (free for evaluation):

```
JLinkRTTLogger -Device <DEVICE> -If SWD -Speed 4000 -RTTChannel 0 rtt.log
```

Or open J-Link RTT Viewer GUI and connect to the same chip.

## Note
This is a stripped subset (printf out + 1-byte input). For multi-buffer
RTT replace `SEGGER_RTT.c` with the upstream version from
<https://www.segger.com/downloads/jlink/SEGGER_RTT.zip>.
'''


def emit(project_dir: str) -> int:
    """Write SEGGER_RTT.[ch] + RTT.md into the project's Drive/RTT folder.
    Returns the number of files written."""
    rtt_dir = os.path.join(project_dir, "Drive", "RTT")
    os.makedirs(rtt_dir, exist_ok=True)
    files = {
        "SEGGER_RTT.h": _RTT_H,
        "SEGGER_RTT.c": _RTT_C,
        "RTT.md":       _README,
    }
    for name, content in files.items():
        with open(os.path.join(rtt_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    print(f"Wrote {len(files)} RTT files to {rtt_dir}")
    print("Add SEGGER_RTT.c to your Keil 'Drive' group "
          "(via uvprojx_modifier.py add-group) and include "
          f"\"{os.path.relpath(rtt_dir, project_dir)}\" on your IncludePath.")
    return len(files)


def view(chip: Optional[str], log_path: str = "rtt.log") -> int:
    """Spawn JLinkRTTLogger pointed at `chip`."""
    jl = find_jlink_exe()
    if not jl:
        print("J-Link not installed. RTT viewing requires Segger J-Link.")
        return 1
    logger = os.path.join(os.path.dirname(jl), "JLinkRTTLogger.exe")
    if not os.path.isfile(logger):
        print(f"JLinkRTTLogger.exe not found beside {jl}")
        return 1

    if not chip:
        print("--chip required so J-Link can pick the right Device.")
        return 1
    db = load_chip_db()
    device = db.get(chip, {}).get("device", chip).rstrip("xX")

    cmd = [logger, "-Device", device, "-If", "SWD", "-Speed", "4000",
           "-RTTChannel", "0", log_path]
    print("Running:", " ".join(cmd))
    rc, out, err = run_command(cmd, timeout=3600)
    print(out)
    print(err)
    return rc


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RTT helper")
    sub = parser.add_subparsers(dest="cmd")

    e = sub.add_parser("emit", help="Drop SEGGER_RTT files into a project")
    e.add_argument("--project", required=True, help="Project root directory")

    v = sub.add_parser("view", help="Launch JLinkRTTLogger")
    v.add_argument("--chip", required=True)
    v.add_argument("--log", default="rtt.log")

    args = parser.parse_args()
    if args.cmd == "emit":
        sys.exit(0 if emit(args.project) else 1)
    elif args.cmd == "view":
        sys.exit(view(args.chip, args.log))
    else:
        parser.print_help()
