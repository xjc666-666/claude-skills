"""
Parse and modify MSPM0 .syscfg JavaScript configuration files.
Uses regex-based parsing and line-level editing.
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import normalize_path, load_hardware_pin_map, load_peripheral_db


class SysConfig:
    """Represents a parsed .syscfg file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lines: List[str] = []
        self.modules: Dict[str, Dict] = {}     # module_var -> {path, instances}
        self.instances: Dict[str, Dict] = {}    # instance_var -> {module_var, name, pins, config}
        self.clock_tree: Dict[str, Dict] = {}   # node_name -> {var_name, properties}
        self.pin_assignments: Dict[str, str] = {}  # pin -> peripheral_name

    def load(self) -> bool:
        """Parse the .syscfg file."""
        if not os.path.isfile(self.filepath):
            return False
        with open(self.filepath, "r", encoding="utf-8") as f:
            content = f.read()
        self.lines = content.split("\n")

        # Parse module imports
        self._parse_modules(content)
        # Parse instances
        self._parse_instances(content)
        # Parse pin assignments
        self._parse_pins(content)
        # Parse clock tree
        self._parse_clock_tree(content)

        return True

    def _parse_modules(self, content: str) -> None:
        """Extract module imports: const GPIO = scripting.addModule("/ti/driverlib/GPIO", {}, false);"""
        pattern = r'const\s+(\w+)\s*=\s*scripting\.addModule\("([^"]+)",\s*(\{[^}]*\})\s*,\s*(\w+)\);'
        for m in re.finditer(pattern, content):
            self.modules[m.group(1)] = {
                "path": m.group(2),
                "args": m.group(3),
                "instance_factory": m.group(4),
            }

    def _parse_instances(self, content: str) -> None:
        """Extract instances: const GPIO1 = GPIO.addInstance();
        And their names: GPIO1.$name = "OLED";"""
        # Instance creation
        inst_pattern = r'const\s+(\w+)\s*=\s*(\w+)\.addInstance\(\);'
        for m in re.finditer(inst_pattern, content):
            inst_var = m.group(1)
            module_var = m.group(2)
            self.instances[inst_var] = {
                "module_var": module_var,
                "name": inst_var,
                "pins": [],
                "config": {},
            }

        # Instance names: SPI1.$name = "SPI_0";
        name_pattern = r'(\w+)\.\$name\s*=\s*"([^"]+)";'
        for m in re.finditer(name_pattern, content):
            inst_var = m.group(1)
            name = m.group(2)
            if inst_var in self.instances:
                self.instances[inst_var]["name"] = name

        # Associated pins: GPIO1.associatedPins.create(3);
        pin_create_pattern = r'(\w+)\.associatedPins\.create\((\d+)\);'
        for m in re.finditer(pin_create_pattern, content):
            inst_var = m.group(1)
            count = int(m.group(2))
            if inst_var in self.instances:
                self.instances[inst_var]["pin_count"] = count

        # Peripheral assignment: SPI1.peripheral.$assign = "SPI0";
        periph_pattern = r'(\w+)\.peripheral\.\$assign\s*=\s*"([^"]+)";'
        for m in re.finditer(periph_pattern, content):
            inst_var = m.group(1)
            periph = m.group(2)
            if inst_var in self.instances:
                self.instances[inst_var]["peripheral"] = periph

        # Target bitrate: SPI1.targetBitRate = 20000000;
        bitrate_pattern = r'(\w+)\.targetBitRate\s*=\s*(\d+);'
        for m in re.finditer(bitrate_pattern, content):
            inst_var = m.group(1)
            if inst_var in self.instances:
                self.instances[inst_var]["config"]["targetBitRate"] = int(m.group(2))

        # Baud rate: UART1.targetBaudRate = 115200;
        baud_pattern = r'(\w+)\.targetBaudRate\s*=\s*(\d+);'
        for m in re.finditer(baud_pattern, content):
            inst_var = m.group(1)
            if inst_var in self.instances:
                self.instances[inst_var]["config"]["targetBaudRate"] = int(m.group(2))

    def _parse_pins(self, content: str) -> None:
        """Extract pin assignments."""
        # GPIO associated pins: GPIO1.associatedPins[0].pin.$assign = "PB23";
        # Peripheral pins: SPI1.peripheral.sclkPin.$assign = "PB3";
        pin_pattern = r'(\w+(?:\.\w+\[\d+\]\.\w+(?:\.\w+)?)?(?:\.peripheral)?)\.(\w+(?:Pin)?)\.\$assign\s*=\s*"([A-Z]\w*)"'

        # Simpler: just find all .$assign = "PXxx" patterns
        simple_pattern = r'(?:\.peripheral\.)?(\w+)\.\$assign\s*=\s*"((?:P[A-C]\d+))"'
        for m in re.finditer(simple_pattern, content):
            sig = m.group(1)
            pin = m.group(2)
            # Skip non-GPIO assignments (like "SPI0", "SYSCTL")
            if not re.match(r'^P[A-C]\d+$', pin):
                continue
            self.pin_assignments[pin] = sig

        # Also capture named pin assignments: pinFunction4.peripheral.hfxInPin.$assign = "PA5"
        named_pin_pattern = r'(\w+)\.(\w+)\.\$assign\s*=\s*"(P[A-C]\d+)"'
        for m in re.finditer(named_pin_pattern, content):
            var_name = m.group(1)
            pin_name = m.group(2)
            pin = m.group(3)
            key = f"{var_name}.{pin_name}"
            self.pin_assignments[pin] = key

    def _parse_clock_tree(self, content: str) -> None:
        """Extract clock tree configuration."""
        # const divider2 = system.clockTree["HFCLK4MFPCLKDIV"];
        node_pattern = r'const\s+(\w+)\s*=\s*system\.clockTree\["([^"]+)"\];'
        node_vars = {}  # var_name -> node_name
        for m in re.finditer(node_pattern, content):
            node_vars[m.group(1)] = m.group(2)
            self.clock_tree[m.group(2)] = {"var_name": m.group(1), "properties": {}}

        # Property assignments: divider2.divideValue = 10;
        # Also things like: pinFunction4.enable = true;
        for var_name, node_name in node_vars.items():
            prop_pattern = rf'{re.escape(var_name)}\.(\w+)\s*=\s*([^;]+);'
            for m in re.finditer(prop_pattern, content):
                prop = m.group(1)
                val_str = m.group(2).strip()
                # Parse the value
                if val_str == "true":
                    val = True
                elif val_str == "false":
                    val = False
                elif re.match(r'^\d+$', val_str):
                    val = int(val_str)
                elif re.match(r'^\d+\.\d+$', val_str):
                    val = float(val_str)
                else:
                    val = val_str.strip('"')
                if node_name in self.clock_tree:
                    self.clock_tree[node_name]["properties"][prop] = val

    # ========== Modification methods ==========

    def add_peripheral(self, module_path: str, instance_config: Dict) -> Dict:
        """Add a new peripheral instance to the syscfg.
        instance_config example:
        {"module":"/ti/driverlib/UART","name":"UART_1","peripheral":"UART1",
         "tx":"PB4","rx":"PB5","baud":9600}
        """
        module_name = os.path.basename(module_path)

        # Check if module already imported
        module_var = None
        for var, info in self.modules.items():
            if info["path"] == module_path:
                module_var = var
                break

        if module_var is None:
            # Need to add module import
            return {"success": False, "error": f"Module {module_path} not yet imported. Use add_module first."}

        # Check for duplicate instance name
        inst_name = instance_config.get("name", "")
        for info in self.instances.values():
            if info.get("name") == inst_name:
                return {"success": False, "error": f"Instance '{inst_name}' already exists"}

        # Generate next instance variable name
        inst_num = self._next_instance_num(module_var)
        inst_var = f"{module_var}{inst_num}"

        # Check hardware-fixed pin conflicts
        hw = load_hardware_pin_map()
        reserved = hw.get("reserved_pins", [])
        for key, val in instance_config.items():
            if re.match(r'^P[A-C]\d+$', str(val)) and val in reserved:
                reason = hw.get("reserved_pins_reason", {}).get(val, "硬件固定")
                return {
                    "success": False,
                    "error": f"引脚 {val} 已被占用: {reason}。请选择其他引脚。",
                    "reserved_pin": val,
                }

        # Build JS lines for the new instance
        new_lines = []
        new_lines.append(f"{inst_var} = {module_var}.addInstance();")
        new_lines.append(f'{inst_var}.$name = "{inst_name}";')

        # Peripheral assignment
        if "peripheral" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.$assign = "{instance_config["peripheral"]}";')

        # Pin assignments
        if "tx" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.txPin.$assign = "{instance_config["tx"]}";')
        if "rx" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.rxPin.$assign = "{instance_config["rx"]}";')
        if "sclk" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.sclkPin.$assign = "{instance_config["sclk"]}";')
        if "mosi" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.mosiPin.$assign = "{instance_config["mosi"]}";')
        if "miso" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.misoPin.$assign = "{instance_config["miso"]}";')
        if "sda" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.sdaPin.$assign = "{instance_config["sda"]}";')
        if "scl" in instance_config:
            new_lines.append(f'{inst_var}.peripheral.sclPin.$assign = "{instance_config["scl"]}";')

        # Bitrate/baud
        if "baud" in instance_config:
            new_lines.append(f'{inst_var}.targetBaudRate = {instance_config["baud"]};')
        if "bitrate" in instance_config:
            new_lines.append(f'{inst_var}.targetBitRate = {instance_config["bitrate"]};')

        # Other common properties
        for prop in ["frameFormat", "polarity", "phase", "direction", "mode",
                      "samplingOperationMode", "dacOutput12", "timerCount",
                      "clockDivider", "clockPrescale"]:
            if prop in instance_config:
                val = instance_config[prop]
                if isinstance(val, str):
                    new_lines.append(f'{inst_var}.{prop} = "{val}";')
                else:
                    new_lines.append(f'{inst_var}.{prop} = {val};')

        # Interrupts
        if "interrupts" in instance_config:
            irq = instance_config["interrupts"]
            if isinstance(irq, list):
                irq_str = ", ".join(f'"{i}"' for i in irq)
                new_lines.append(f'{inst_var}.enabledInterrupts = [{irq_str}];')

        # Insert into file after the last instance creation line
        insert_idx = self._find_last_instance_line()
        if insert_idx >= 0:
            for i, line in enumerate(new_lines):
                self.lines.insert(insert_idx + 1 + i, line)
        else:
            self.lines.extend(new_lines)

        # Save
        self._save()

        return {
            "success": True,
            "instance_var": inst_var,
            "instance_name": inst_name,
            "added_lines": new_lines,
        }

    def remove_peripheral(self, instance_name: str) -> Dict:
        """Remove a peripheral instance by its $name."""
        removed = []
        for inst_var, info in list(self.instances.items()):
            if info.get("name") == instance_name:
                # Remove all lines referencing this instance
                new_lines = []
                for line in self.lines:
                    # Skip lines that start with this variable name
                    trimmed = line.strip()
                    if trimmed.startswith(f"{inst_var}.") or \
                       trimmed.startswith(f"const {inst_var}") or \
                       trimmed.startswith(f"{inst_var} ="):
                        removed.append(line)
                        continue
                    new_lines.append(line)
                self.lines = new_lines
                del self.instances[inst_var]
                self._save()
                return {
                    "success": True,
                    "instance_var": inst_var,
                    "instance_name": instance_name,
                    "removed_lines": removed,
                }

        return {"success": False, "error": f"Instance '{instance_name}' not found"}

    def modify_clock(self, node_name: str, property_name: str, value) -> Dict:
        """Modify a clock tree node property."""
        if node_name not in self.clock_tree:
            return {"success": False, "error": f"Clock node '{node_name}' not in syscfg"}

        var_name = self.clock_tree[node_name].get("var_name", "")
        if not var_name:
            return {"success": False, "error": f"No variable for clock node '{node_name}'"}

        # Format the value
        if isinstance(value, bool):
            val_str = "true" if value else "false"
        elif isinstance(value, str):
            val_str = f'"{value}"'
        else:
            val_str = str(value)

        new_line = f'{var_name}.{property_name} = {val_str};'

        # Find and replace the existing line
        found = False
        for i, line in enumerate(self.lines):
            if f"{var_name}.{property_name}" in line and "=" in line:
                self.lines[i] = new_line
                found = True
                break

        if not found:
            # Append after the node declaration
            for i, line in enumerate(self.lines):
                if f'system.clockTree["{node_name}"]' in line:
                    self.lines.insert(i + 1, new_line)
                    found = True
                    break

        if not found:
            self.lines.append(new_line)

        self._save()
        return {"success": True, "node": node_name, "property": property_name, "value": value}

    def check_conflicts(self) -> List[Dict]:
        """Check for pin assignment conflicts."""
        hw = load_hardware_pin_map()
        conflicts = []

        # Count pin usage
        pin_users: Dict[str, List[str]] = {}
        for pin, sig in self.pin_assignments.items():
            if pin not in pin_users:
                pin_users[pin] = []
            pin_users[pin].append(sig)

        # Check for multi-use pins
        for pin, users in pin_users.items():
            if len(users) > 1:
                conflicts.append({
                    "type": "MULTI_USE",
                    "pin": pin,
                    "users": users,
                    "severity": "CONFLICT",
                    "message": f"引脚 {pin} 被多个功能使用: {', '.join(users)}",
                })

            # Check against reserved pins
            reserved = hw.get("reserved_pins", [])
            if pin in reserved:
                reason = hw.get("reserved_pins_reason", {}).get(pin, "硬件固定")
                conflicts.append({
                    "type": "RESERVED",
                    "pin": pin,
                    "users": users,
                    "reason": reason,
                    "severity": "WARNING",
                    "message": f"引脚 {pin} 为 {reason}",
                })

        # Check OLED fixed pins
        oled = hw.get("fixed_pins", {}).get("OLED", {})
        oled_pins_in_syscfg = []
        for key in ["sclk", "mosi", "cs", "dc", "res"]:
            expected = oled.get(key)
            if expected and expected in pin_users:
                oled_pins_in_syscfg.append(expected)

        return conflicts

    def list_modules(self) -> List[Dict]:
        """List all modules and instances."""
        result = []
        for var, info in self.modules.items():
            insts = []
            for ivar, iinfo in self.instances.items():
                if iinfo.get("module_var") == var:
                    insts.append({
                        "var": ivar,
                        "name": iinfo.get("name", ivar),
                        "peripheral": iinfo.get("peripheral", ""),
                        "pins": iinfo.get("pins", []),
                        "config": iinfo.get("config", {}),
                    })
            result.append({
                "module_var": var,
                "module_path": info["path"],
                "instances": insts,
            })
        return result

    def list_pins(self) -> Dict[str, str]:
        """Return pin assignments dict."""
        return dict(self.pin_assignments)

    def list_clock(self) -> Dict[str, Dict]:
        """Return clock tree configuration."""
        return dict(self.clock_tree)

    def _next_instance_num(self, module_var: str) -> int:
        """Find next available instance number for a module."""
        max_num = 0
        for ivar in self.instances:
            if ivar.startswith(module_var):
                try:
                    num = int(ivar[len(module_var):])
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        return max_num + 1

    def _find_last_instance_line(self) -> int:
        """Find the line index of the last addInstance() call."""
        for i in range(len(self.lines) - 1, -1, -1):
            if ".addInstance()" in self.lines[i]:
                return i
        # Fallback: find end of module imports section
        for i, line in enumerate(self.lines):
            if "Write custom configuration" in line:
                return i + 1
        return len(self.lines) - 1

    def _save(self) -> None:
        """Write modified content back to file."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse/modify MSPM0 .syscfg files")
    parser.add_argument("--syscfg", required=True, help="Path to config.syscfg")
    parser.add_argument("--list-modules", action="store_true")
    parser.add_argument("--list-pins", action="store_true")
    parser.add_argument("--list-clock", action="store_true")
    parser.add_argument("--check-conflicts", action="store_true")
    parser.add_argument("--add-peripheral", default=None, help="JSON config for new peripheral")
    parser.add_argument("--remove-peripheral", default=None, help="Instance name to remove")
    parser.add_argument("--modify-clock", default=None, help="JSON: {node, property, value}")

    args = parser.parse_args()

    cfg = SysConfig(args.syscfg)
    if not cfg.load():
        print(json.dumps({"error": f"Failed to load {args.syscfg}"}))
        sys.exit(1)

    if args.list_modules:
        print(json.dumps(cfg.list_modules(), indent=2, ensure_ascii=False))
    elif args.list_pins:
        print(json.dumps(cfg.list_pins(), indent=2, ensure_ascii=False))
    elif args.list_clock:
        print(json.dumps(cfg.list_clock(), indent=2, ensure_ascii=False))
    elif args.check_conflicts:
        print(json.dumps(cfg.check_conflicts(), indent=2, ensure_ascii=False))
    elif args.add_peripheral:
        config = json.loads(args.add_peripheral)
        result = cfg.add_peripheral(
            config.get("module", ""),
            config,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.remove_peripheral:
        result = cfg.remove_peripheral(args.remove_peripheral)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.modify_clock:
        clock_config = json.loads(args.modify_clock)
        result = cfg.modify_clock(
            clock_config.get("node", ""),
            clock_config.get("property", ""),
            clock_config.get("value", ""),
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        parser.print_help()
