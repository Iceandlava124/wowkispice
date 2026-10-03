"""
cad_engine.py - Interactive CAD Schematic, Netlist Generator & EDA Exporter
Provides:
1. Component & Pin Graph Database with dynamic terminal routing
2. Visual to SPICE Netlist Compiler
3. KiCad Schematic (.kicad_sch) & LTspice (.cir / .asc) Exporters
4. Bill of Materials (BOM) Generator with DigiKey/LCSC Part Number & Costing
"""

import os
import re
import sys
import json
from typing import Dict, List, Any, Tuple, Optional


class SchematicComponent:
    def __init__(
        self,
        comp_id: str,
        comp_type: str,
        name: str,
        value: str,
        x: float,
        y: float,
        footprint: str = "",
        mpn: str = "",
        cost_usd: float = 0.0,
        pins: Optional[Dict[str, str]] = None,
        rotation: float = 0.0
    ):
        self.comp_id = comp_id
        self.comp_type = comp_type
        self.name = name
        self.value = value
        self.x = x
        self.y = y
        self.footprint = footprint
        self.mpn = mpn
        self.cost_usd = cost_usd
        # Dict mapping pin_name -> net_name
        self.pins = pins or {}
        # Editor rotation in degrees (0/90/180/270); geometry only, not used by the netlister
        self.rotation = rotation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comp_id": self.comp_id,
            "comp_type": self.comp_type,
            "name": self.name,
            "value": self.value,
            "x": self.x,
            "y": self.y,
            "footprint": self.footprint,
            "mpn": self.mpn,
            "cost_usd": self.cost_usd,
            "pins": self.pins,
            "rotation": self.rotation
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchematicComponent":
        return cls(
            comp_id=data.get("comp_id", ""),
            comp_type=data.get("comp_type", "R"),
            name=data.get("name", "R1"),
            value=data.get("value", "10k"),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            footprint=data.get("footprint", ""),
            mpn=data.get("mpn", ""),
            cost_usd=data.get("cost_usd", 0.0),
            pins=data.get("pins", {}),
            rotation=data.get("rotation", 0.0)
        )


# Component types that behave as an MCU for netlisting purposes. Board-specific
# symbols (Arduino Uno, STM32F103, ...) differ only in their pin names; the
# compiler treats them all the same way.
MCU_TYPES = frozenset({
    "MCU", "ESP32", "ESP32S3", "ARDUINO_UNO", "ARDUINO_NANO", "ARDUINO_MEGA",
    "STM32F103", "STM32F407", "STM32L4", "RP2040", "CUSTOM",
})


def is_mcu(comp_type: str) -> bool:
    """True when this component type is an MCU for netlisting purposes."""
    return str(comp_type or "").upper() in MCU_TYPES


def generate_bom_for(model: "SchematicNetlistEngine") -> List[Dict[str, Any]]:
    """
    Build a BOM from an actual schematic graph (one row per placed component).

    Distinct from SchematicNetlistEngine.generate_bom(), which returns the
    legacy hard-coded reference buck converter BOM.
    """
    rows: List[Dict[str, Any]] = []
    for comp in sorted(model.components.values(), key=lambda c: c.name):
        ctype = comp.comp_type.upper()
        if ctype == "GND":
            continue
        rows.append({
            "Designator": comp.name,
            "Type": comp.comp_type,
            "Value": comp.value or "(default)",
            "Footprint": comp.footprint or "-",
            "MPN": comp.mpn or "-",
            "Qty": 1,
            "Unit Cost (USD)": comp.cost_usd,
            "Extended Cost": comp.cost_usd,
        })
    return rows


class SchematicNetlistEngine:
    def __init__(self):
        self.components: Dict[str, SchematicComponent] = {}
        self.wires: List[Dict[str, Any]] = []
        # Per-MCU declared pin behaviour: {comp_id: {pin_name: profile}}
        self.gpio_profiles: Dict[str, Dict[str, Any]] = {}
        # Per-MCU closed-loop control law: {comp_id: {spec...}}
        # A law makes its pin an `external` source driven by the solver
        # (see bridge/cosim_runner.py).
        self.control_laws: Dict[str, Dict[str, Any]] = {}
        # Firmware metadata per MCU: {comp_id: {...FirmwareImage.to_dict()...}}
        self.firmware: Dict[str, Dict[str, Any]] = {}

    def clear(self):
        self.components.clear()
        self.wires.clear()
        self.gpio_profiles.clear()
        self.control_laws.clear()
        self.firmware.clear()

    def add_component(self, comp: SchematicComponent):
        self.components[comp.comp_id] = comp

    def remove_component(self, comp_id: str):
        if comp_id in self.components:
            del self.components[comp_id]
        # Remove attached wires
        self.wires = [
            w for w in self.wires
            if not (w["from"].startswith(comp_id + ":") or w["to"].startswith(comp_id + ":"))
        ]

    def add_wire(self, pin_from: str, pin_to: str, net_name: Optional[str] = None):
        """Add a wire between two component pins (e.g. 'R1:1' -> 'C1:1')."""
        net = net_name or f"NET_{len(self.wires) + 1}"
        self.wires.append({
            "from": pin_from,
            "to": pin_to,
            "net": net
        })
        
        # Assign pins to net
        if ":" in pin_from:
            cid, pin = pin_from.split(":", 1)
            if cid in self.components:
                self.components[cid].pins[pin] = net
        if ":" in pin_to:
            cid, pin = pin_to.split(":", 1)
            if cid in self.components:
                self.components[cid].pins[pin] = net

    # ------------------------------------------------------------------
    # Graph -> SPICE netlist compilation
    # ------------------------------------------------------------------

    # Canonical pin order per passive/source type (aliases normalized to these)
    _CANONICAL_PINS: Dict[str, List[str]] = {
        "R": ["1", "2"],
        "C": ["1", "2"],
        "L": ["1", "2"],
        "V": ["+", "-"],
        "I": ["+", "-"],
        "D": ["A", "K"],
        "MOSFET": ["D", "G", "S"],
        "SWITCH": ["1", "2"],
        "GND": ["1"],
    }

    _PIN_ALIASES: Dict[str, str] = {
        "GATE": "G", "DRAIN": "D", "DRN": "D", "SOURCE": "S", "SRC": "S",
        "ANODE": "A", "CATHODE": "K", "KATHODE": "K",
        "PLUS": "+", "MINUS": "-", "P": "+", "N": "-",
        "IN": "1", "OUT": "2", "A": "1", "B": "2",
    }

    # SPICE element leading letter required by the parser for each type
    _ELEMENT_LETTERS = {"R": "R", "C": "C", "L": "L", "V": "V", "I": "I",
                        "D": "D", "MOSFET": "M", "SWITCH": "S"}

    _DEFAULT_VALUES = {"R": "1k", "C": "1n", "L": "1u", "V": "0", "I": "0",
                       "D": "D_MODEL", "MOSFET": "NMOS_MODEL", "SWITCH": "SW_MODEL"}

    def compile_netlist(
        self,
        vin: float = 12.0,
        tstep_us: float = 0.5,
        duration_ms: float = 5.0,
        analysis: str = "tran",
        mcu_pins: str = "drive",
        ac_start_hz: float = 1.0,
        ac_stop_hz: float = 1e6,
        ac_points_per_decade: int = 20,
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Compile the schematic component graph into an executable SPICE netlist.

        Returns (netlist_lines, probeable_net_names, warnings).
        Nets are resolved with a union-find over wires (so chained wires
        A-B, B-C collapse into one electrical node) and ground is node "0".
        An empty schematic falls back to the legacy reference buck converter.

        `analysis` selects the analysis card: "tran" for the usual transient
        run, "ac" for a small-signal frequency sweep (which also stamps AC 1 on
        the first independent source, since .ac ignores DC values).

        `mcu_pins` controls the MCU symbols in a "Transient only" run: "drive"
        emits each wired pin as a source, "ignore" leaves them undriven and says
        so in a comment, so a pure-analog run really is pure analog.
        """
        analysis = (analysis or "tran").lower()
        if analysis not in ("tran", "ac"):
            raise ValueError(f"unknown analysis '{analysis}' (use 'tran' or 'ac')")
        mcu_pins = (mcu_pins or "drive").lower()
        if mcu_pins not in ("drive", "ignore"):
            raise ValueError(
                f"unknown mcu_pins mode '{mcu_pins}' (use 'drive' or 'ignore')")
        if not self.components:
            legacy = self._legacy_reference_netlist(vin, tstep_us, duration_ms)
            return legacy, ["in", "sw_node", "vout"], []

        net_of, ground_nets = self._resolve_nets()
        warnings: List[str] = []
        lines: List[str] = [
            "* WOWKISPICE CAD Netlist - compiled from schematic graph",
            f"* {len(self.components)} component(s), {len(self.wires)} wire(s)",
        ]

        models_needed: List[str] = []
        has_source = False
        emitted = 0
        ac_marked = False

        for comp in sorted(self.components.values(), key=lambda c: c.name):
            ctype = comp.comp_type.upper()
            if ctype in ("GND", "GROUND"):
                continue  # ground is expressed by node name "0"
            if is_mcu(ctype):
                mcu_lines, mcu_sources = self._emit_mcu(comp, net_of, warnings,
                                                         mcu_pins=mcu_pins)
                lines.extend(mcu_lines)
                has_source = has_source or mcu_sources > 0
                continue

            letter = self._ELEMENT_LETTERS.get(ctype)
            if letter is None:
                lines.append(f"* unsupported component {comp.name} ({comp.comp_type}) - skipped")
                warnings.append(f"Component {comp.name} ({comp.comp_type}) is not SPICE-simulatable; skipped.")
                continue

            canon = self._CANONICAL_PINS.get(ctype, ["1", "2"])
            pin_nets = self._ordered_pin_nets(comp, canon, net_of)
            if comp.name[:1].upper() == letter:
                designator = comp.name
            elif comp.comp_id[:1].upper() == letter:
                designator = comp.comp_id
            else:
                designator = letter + comp.comp_id  # e.g. Q1 -> MQ1 (SPICE needs the type letter)
            value = (comp.value or "").strip() or self._DEFAULT_VALUES.get(ctype, "0")

            if ctype in ("V", "I"):
                has_source = True
                if re.fullmatch(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?", value):
                    card = f"DC {value}"
                else:
                    card = value  # PULSE(...), PWL(...), SIN(...) pass through verbatim
                if analysis == "ac" and not ac_marked:
                    # .ac drives the first independent source with its AC
                    # magnitude; without this the sweep has nothing to excite.
                    card = f"{card} AC 1"
                    ac_marked = True
                lines.append(f"{designator} {' '.join(pin_nets)} {card}")
            elif ctype == "D":
                models_needed.append("D_MODEL")
                lines.append(f"{designator} {' '.join(pin_nets)} D_MODEL")
            elif ctype == "MOSFET":
                models_needed.append("NMOS_MODEL")
                if len(pin_nets) == 4:
                    lines.append(f"{designator} {' '.join(pin_nets)} NMOS_MODEL")
                else:
                    d, g, s = pin_nets
                    lines.append(f"{designator} {d} {g} {s} {s} NMOS_MODEL")  # bulk tied to source
            elif ctype == "SWITCH":
                models_needed.append("SW_MODEL")
                ctrl = self._net(net_of, comp.comp_id, "CTRL", f"{comp.name}_ctrl")
                n1, n2 = pin_nets
                lines.append(f"{designator} {n1} {n2} {ctrl} 0 SW_MODEL")
            else:
                lines.append(f"{designator} {' '.join(pin_nets)} {value}")
            emitted += 1

        if "D_MODEL" in models_needed:
            lines.append(".model D_MODEL D(IS=1e-14 N=1 RS=0.1 BV=100 IBV=1e-3)")
        if "NMOS_MODEL" in models_needed:
            lines.append(".model NMOS_MODEL NMOS(VTO=2.0 KP=20)")
        if "SW_MODEL" in models_needed:
            lines.append(".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)")

        # -- electrical sanity checks -> actionable warnings for the editor console
        if not ground_nets:
            warnings.append("No ground node: place a GND symbol (or name a net '0'/'GND') before running.")
        if not has_source:
            warnings.append("No independent source (V/I): simulation output will be all zeros.")
        elif analysis == "ac" and not ac_marked:
            warnings.append(
                "AC analysis needs an independent V/I source; none was stamped with "
                "an AC magnitude, so the sweep has no excitation.")
        for cid, comp in sorted(self.components.items()):
            ctype = comp.comp_type.upper()
            canonical = self._CANONICAL_PINS.get(ctype)
            if not canonical or ctype == "GND" or is_mcu(ctype):
                continue
            filled = set(comp.pins) | {self._canon_pin(p) for p in comp.pins}
            for pin in canonical:
                if pin not in filled:
                    warnings.append(f"Pin {comp.name}.{pin} is unconnected.")

        if analysis == "ac":
            lines.append(f".ac dec {int(ac_points_per_decade)} "
                         f"{ac_start_hz:g} {ac_stop_hz:g}")
        else:
            lines.append(f".tran {tstep_us:.2f}u {duration_ms:.1f}m uic")
        lines.append(".end")

        probe_nets = sorted({n for n in net_of.values() if n and n != "0" and not n.startswith("__")})
        return lines, probe_nets, warnings

    def _emit_mcu(self, comp: SchematicComponent, net_of, warnings: List[str],
                 mcu_pins: str = "drive") -> Tuple[List[str], int]:
        """
        Emit an MCU as a comment plus one real voltage source per wired output pin.

        Pins drive their net with the declared GPIO profile (bridge/gpio_model).
        A pin carrying a closed-loop control law instead emits an `external`
        source, which bridge/cosim_runner.py drives from inside the solver.
        Unprofiled output pins idle LOW and say so, rather than floating the net.
        Pins named GND/0 stay as ground and emit nothing.
        """
        from bridge import control_law, gpio_model

        label = comp.value.strip() or comp.name
        profile = self.gpio_profiles.get(comp.comp_id, {})
        firmware = self.firmware.get(comp.comp_id)
        out = [f"* MCU {comp.comp_id} ({label}) - co-simulation digital source"]
        if firmware:
            out.append(f"*   firmware: {firmware.get('name', '?')}, "
                       f"{firmware.get('size_bytes', 0)} bytes, "
                       f"sha256 {str(firmware.get('sha256', ''))[:12]}")
        law = self.control_laws.get(comp.comp_id)
        if not law:
            out.append("*   NOTE: pin behaviour comes from a declared profile, "
                       "not from executing the binary")
        if law:
            try:
                out.append(f"*   CONTROL LAW on {law.get('pin')}: "
                           f"{control_law.describe_law(law)}")
                out.append(f"*   source below is `external`: ngspice calls back into "
                           f"bridge/cosim_runner.py so the pin tracks the simulated "
                           f"feedback net '{law.get('sense_net')}'")
            except Exception as exc:                     # never break netlisting
                warnings.append(f"{comp.comp_id} control law not describable ({exc}).")

        sources = 0
        law_pin = (law or {}).get("pin")
        if mcu_pins == "ignore":
            out.append(f"*   MCU pins are NOT driven (transient-only mode): "
                       f"{len(comp.pins)} pin(s) left undriven, run is pure analog")
            for pin in sorted(comp.pins):
                node = net_of.get((comp.comp_id, pin), f"{comp.comp_id}_{self._safe(pin)}")
                out.append(f"*     {pin} -> {'ground (node 0)' if node == '0' else 'net ' + node}")
            return out, 0
        for pin in sorted(comp.pins):
            node = net_of.get((comp.comp_id, pin), f"{comp.comp_id}_{self._safe(pin)}")
            if node == "0" or pin in ("GND", "0", "gnd"):
                out.append(f"*   {pin} -> ground (node 0)")
                continue
            designator = f"V{self._safe(comp.comp_id)}_{self._safe(pin)}"
            if law and pin == law_pin:
                # Driven by the solver, not by a fixed waveform.
                out.append(f"{designator} {node} 0 external")
                sources += 1
                continue
            spec = profile.get(pin)
            try:
                card = gpio_model.spice_card(spec)
            except ValueError as exc:
                warnings.append(f"{comp.comp_id}.{pin} profile invalid ({exc}); pin left undriven.")
                continue
            out.append(f"{designator} {node} 0 {card}")
            sources += 1
            if not spec:                     # None *or* an empty profile both mean undeclared
                warnings.append(
                    f"{comp.comp_id}.{pin} has no GPIO profile; assumed idle LOW "
                    f"(set one for real behaviour).")
            out.append(f"*   {gpio_model.describe_pin(pin, spec)}")
        if not comp.pins:
            out.append("*   no pins wired")
        if law and law_pin not in comp.pins:
            warnings.append(
                f"{comp.comp_id} control law targets pin '{law_pin}', which is not wired; "
                f"the law cannot run.")
        return out, sources

    def _legacy_reference_netlist(self, vin: float, tstep_us: float, duration_ms: float) -> List[str]:
        """Empty-schematic fallback: the reference 12V->3.3V buck (keeps legacy export behavior)."""
        return [
            "* WOWKISPICE Reference Buck Converter (empty schematic fallback)",
            f"Vin in 0 DC {vin:.2f}",
            "Vgate gate 0 dc 0 external",
            "S1 in sw_node gate 0 SW_MODEL",
            "D1 0 sw_node DIODE_MODEL",
            "L1 sw_node vout 47u IC=0",
            "C1 vout 0 100u IC=0",
            "Rload vout 0 5.0",
            ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)",
            ".model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)",
            f".tran {tstep_us:.2f}u {duration_ms:.1f}m uic",
            ".end",
        ]

    @staticmethod
    def _canon_pin(pin: str) -> str:
        p = pin.strip()
        if p in ("0", "GND", "gnd"):
            return p
        return SchematicNetlistEngine._PIN_ALIASES.get(p.upper(), p)

    @staticmethod
    def _net(net_of: Dict[Tuple[str, str], str], cid: str, pin: str, fallback: str) -> str:
        return net_of.get((cid, pin), fallback)

    def _ordered_pin_nets(
        self,
        comp: SchematicComponent,
        canonical: List[str],
        net_of: Dict[Tuple[str, str], str],
    ) -> List[str]:
        """
        Resolve this component's pin nets in canonical order.
        Actual pin names are matched alias-aware ('GATE'->'G', 'A'->'1', ...);
        canonical slots left unfilled take leftover wired pins in order, which
        keeps nonstandard pin naming schemes (A/B passives, diode anode) working.
        """
        actuals = list(comp.pins)
        if not actuals:
            return [f"{comp.comp_id}_{self._safe(c)}" for c in canonical]

        pairs: List[Optional[str]] = []
        used = set()
        for canon in canonical:
            match = next((a for a in actuals
                          if a not in used and self._canon_pin(a) == canon), None)
            pairs.append(match)
            if match:
                used.add(match)
        leftovers = [a for a in actuals if a not in used]
        for i, slot in enumerate(pairs):
            if slot is None and leftovers:
                pairs[i] = leftovers.pop(0)
                used.add(pairs[i])

        ordered: List[str] = []
        for actual, canon in zip(pairs, canonical):
            if actual is None:
                ordered.append(f"{comp.comp_id}_{self._safe(canon)}")
            else:
                ordered.append(net_of.get((comp.comp_id, actual),
                                          f"{comp.comp_id}_{self._safe(actual)}"))
        return ordered

    @staticmethod
    def _safe(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", name)

    def _resolve_nets(self) -> Tuple[Dict[Tuple[str, str], str], List[str]]:
        """
        Union-find over (comp_id, pin) endpoints. Wires merge endpoints;
        identical explicit net names also merge. Returns
        (net_of[(comp_id,pin)] -> net name, list of nets that are ground).
        """
        parent: Dict[Tuple[str, str], Tuple[str, str]] = {}

        def find(x: Tuple[str, str]) -> Tuple[str, str]:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: Tuple[str, str], b: Tuple[str, str]):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        def parse(ref: str) -> Optional[Tuple[str, str]]:
            if ":" not in ref:
                return None
            cid, pin = ref.split(":", 1)
            if cid not in self.components:
                return None
            return (cid, pin)

        # Seed nodes: wire endpoints + pins already recorded on components
        for w in self.wires:
            a, b = parse(w.get("from", "")), parse(w.get("to", ""))
            if a and b:
                union(a, b)
        for comp in self.components.values():
            for pin in comp.pins:
                find((comp.comp_id, pin))

        # Merge pins that share an explicit net name (label-based connectivity)
        by_name: Dict[str, Tuple[str, str]] = {}
        for comp in self.components.values():
            for pin, netname in comp.pins.items():
                if not netname:
                    continue
                node = (comp.comp_id, pin)
                if netname in by_name:
                    union(by_name[netname], node)
                else:
                    by_name[netname] = node

        # Assign names per group: gather label candidates from wire net names
        # (comp.pins keeps only the last wire's label per pin, so wires are the
        # authoritative source of labels) and from pins' declared nets.
        wire_labels: Dict[Tuple[str, str], List[str]] = {}
        for w in self.wires:
            label = (w.get("net") or "").strip()
            if not label:
                continue
            for ref in (w.get("from", ""), w.get("to", "")):
                node = parse(ref)
                if node:
                    wire_labels.setdefault(node, []).append(label)

        groups: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        for node in list(parent):
            groups.setdefault(find(node), []).append(node)

        net_of: Dict[Tuple[str, str], str] = {}
        ground_nets: List[str] = []
        auto_idx = 0
        for root in sorted(groups):
            members = groups[root]
            is_ground = False
            candidates: List[str] = []
            for cid, pin in members:
                comp = self.components[cid]
                if comp.comp_type.upper() in ("GND", "GROUND"):
                    is_ground = True
                if pin in ("0", "GND", "gnd"):
                    is_ground = True
                declared = comp.pins.get(pin, "")
                if declared in ("0", "GND", "gnd"):
                    is_ground = True
                candidates.extend(wire_labels.get((cid, pin), []))
                if declared:
                    candidates.append(declared)
            if is_ground:
                name = "0"
                ground_nets.append(name)
            elif candidates:
                # Prefer human labels (in/out) over auto-generated NET_<n>
                human = [c for c in candidates if not re.fullmatch(r"NET_\d+", c)]
                name = min(human) if human else min(candidates)
            else:
                auto_idx += 1
                name = f"n{auto_idx}"
            for node in members:
                net_of[node] = name
        return net_of, sorted(set(ground_nets))

    # ------------------------------------------------------------------
    # Document persistence (for the editor's save/open/undo)
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        # Copy the pin dicts: undo snapshots must not alias live component state,
        # because add_wire() mutates component.pins in place.
        return {
            "format": "wowki-schematic-v1",
            "components": [
                {**c.to_dict(), "pins": dict(c.pins)}
                for c in self.components.values()
            ],
            "wires": [dict(w) for w in self.wires],
            "gpio_profiles": {k: dict(v) for k, v in self.gpio_profiles.items()},
            "control_laws": {k: dict(v) for k, v in self.control_laws.items()},
            "firmware": {k: dict(v) for k, v in self.firmware.items()},
        }

    def load_dict(self, data: Dict[str, Any]):
        self.clear()
        for cd in data.get("components", []):
            comp = SchematicComponent.from_dict(cd)
            self.components[comp.comp_id] = comp
        self.wires = [dict(w) for w in data.get("wires", [])]
        self.gpio_profiles = {k: dict(v) for k, v in data.get("gpio_profiles", {}).items()}
        self.control_laws = {k: dict(v) for k, v in data.get("control_laws", {}).items()}
        self.firmware = {k: dict(v) for k, v in data.get("firmware", {}).items()}

    def generate_spice_netlist(
        self,
        vin: float = 12.0,
        tstep_us: float = 0.5,
        duration_ms: float = 5.0
    ) -> List[str]:
        """Compile the visual circuit graph into an executable SPICE netlist."""
        lines, _nets, _warnings = self.compile_netlist(vin=vin, tstep_us=tstep_us, duration_ms=duration_ms)
        return lines

    def generate_bom(self) -> List[Dict[str, Any]]:
        """Generate a complete Bill of Materials (BOM) with commercial MPNs and cost."""
        bom = [
            {
                "Designator": "U1",
                "Description": "Dual-Core 240MHz Wi-Fi/BLE MCU",
                "Manufacturer": "Espressif",
                "MPN": "ESP32-WROOM-32E",
                "Package": "Module SMD",
                "Quantity": 1,
                "Unit Cost (USD)": 2.65,
                "Extended Cost": 2.65
            },
            {
                "Designator": "Q1",
                "Description": "100V 33A N-Channel Power MOSFET",
                "Manufacturer": "Infineon / Vishay",
                "MPN": "IRF540NPBF",
                "Package": "TO-220AB",
                "Quantity": 1,
                "Unit Cost (USD)": 0.72,
                "Extended Cost": 0.72
            },
            {
                "Designator": "D1",
                "Description": "40V 1A Schottky Barrier Rectifier",
                "Manufacturer": "ON Semiconductor",
                "MPN": "1N5819",
                "Package": "DO-41",
                "Quantity": 1,
                "Unit Cost (USD)": 0.12,
                "Extended Cost": 0.12
            },
            {
                "Designator": "L1",
                "Description": "47µH 4.5A Shielded Power Inductor",
                "Manufacturer": "Bourns / Wurth",
                "MPN": "SDR1307-470KL",
                "Package": "13x13mm SMD",
                "Quantity": 1,
                "Unit Cost (USD)": 0.58,
                "Extended Cost": 0.58
            },
            {
                "Designator": "C1",
                "Description": "100µF 35V Low-ESR Electrolytic Cap",
                "Manufacturer": "Panasonic / Nichicon",
                "MPN": "EEU-FR1V101",
                "Package": "Radial 8x11.5mm",
                "Quantity": 1,
                "Unit Cost (USD)": 0.28,
                "Extended Cost": 0.28
            },
            {
                "Designator": "R1, R2",
                "Description": "10kΩ 1% 0.25W Precision Metal Film",
                "Manufacturer": "Yageo / Vishay",
                "MPN": "MFR-25FRF52-10K",
                "Package": "Axial 0207",
                "Quantity": 2,
                "Unit Cost (USD)": 0.03,
                "Extended Cost": 0.06
            },
            {
                "Designator": "R_LOAD",
                "Description": "5.0Ω 10W Power Resistor",
                "Manufacturer": "Ohmite",
                "MPN": "280-CR10-5.0-RC",
                "Package": "Ceramic Wirewound",
                "Quantity": 1,
                "Unit Cost (USD)": 0.85,
                "Extended Cost": 0.85
            }
        ]
        return bom

    def export_kicad_schematic(self, output_path: str, origins=None, title: str = "WOSP Schematic"):
        """
        Export this schematic to a KiCad 9/10 schematic file.

        Thin wrapper around bridge.kicad_export, which is verified against a real
        kicad-cli install (see tests/test_kicad_export.py). Raises ValueError on
        an empty schematic instead of emitting a canned reference sheet.
        """
        from bridge.kicad_export import export_kicad_schematic as _export
        return _export(self, output_path, origins=origins, title=title)
