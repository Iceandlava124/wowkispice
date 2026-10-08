"""
ngspice ctypes wrapper for PROJECT_WOWKISPICE
Provides high-level Python interface to libngspice / ngspice.dll with native
high-speed synchronization callbacks (GetVSRCData, GetSyncData, SendData).
"""

import ctypes
import ctypes.util
import os
import sys
import threading
from typing import Callable, Optional, Dict, Any, List, Tuple


def _bundled_dll_path() -> str:
    """The Windows ngspice.dll that ships alongside the repo, if present."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "tools", "ngspice_dll",
                        "Spice64_dll", "dll-vs", "ngspice.dll")


def resolve_ngspice_library(explicit: Optional[str] = None
                            ) -> Tuple[Optional[str], List[str]]:
    """Locate libngspice.

    Resolution order:
      1. `explicit`, if the caller passed one. An explicit request is honoured
         strictly - we never silently substitute a different library for it.
      2. The WOSP_NGSPICE_LIB environment variable, if set.
      3. The bundled Windows ngspice.dll under tools/ngspice_dll/.
      4. Whatever ctypes.util.find_library("ngspice") reports, which covers a
         system-installed ngspice on Linux/macOS (libngspice.so / .dylib).

    Returns (path_or_None, attempted_paths). Path is None only when every
    candidate failed to resolve.
    """
    tried: List[str] = []

    if explicit is not None:
        tried.append(explicit)
        return (explicit if os.path.exists(explicit) else None), tried

    env = os.environ.get("WOSP_NGSPICE_LIB")
    if env:
        tried.append(f"{env} (from $WOSP_NGSPICE_LIB)")
        if os.path.exists(env):
            return env, tried

    bundled = _bundled_dll_path()
    tried.append(bundled)
    if os.path.exists(bundled):
        return bundled, tried

    try:
        system = ctypes.util.find_library("ngspice")
    except Exception:
        system = None
    if system:
        tried.append(system)
        return system, tried

    tried.append("<system search: ctypes.util.find_library('ngspice') -> None>")
    return None, tried


_MISSING_DLL_HELP = (
    "\n\nFix it one of these ways:\n"
    "  * Windows: run setup.ps1 to fetch and place the bundled DLL\n"
    "    (it downloads the official ngspice build automatically)\n"
    "  * Linux/macOS: install ngspice system-wide, e.g.\n"
    "      sudo apt-get install -y ngspice libngspice0\n"
    "      brew install ngspice\n"
    "  * Any platform: point at an existing shared library, either\n"
    "      NgSpiceEngine(dll_path='/full/path/to/libngspice.so')\n"
    "      export WOSP_NGSPICE_LIB=/full/path/to/libngspice.so\n"
)

# Struct definitions from sharedspice.h
class VectorInfo(ctypes.Structure):
    _fields_ = [
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.c_void_p),
        ("v_length", ctypes.c_int)
    ]

class VecValues(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("creal", ctypes.c_double),
        ("cimag", ctypes.c_double),
        ("is_scale", ctypes.c_bool),
        ("is_complex", ctypes.c_bool)
    ]

class VecValuesAll(ctypes.Structure):
    _fields_ = [
        ("veccount", ctypes.c_int),
        ("vecindex", ctypes.c_int),
        ("vecsa", ctypes.POINTER(ctypes.POINTER(VecValues)))
    ]

# Function callback prototypes matching sharedspice.h
SendChar_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
SendStat_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
ControlledExit_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
SendData_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(VecValuesAll), ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
SendInitData_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
BGThreadRunning_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)

GetVSRCData_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
GetISRCData_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
GetSyncData_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_double, ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)


class NgSpiceEngine:
    def __init__(
        self,
        dll_path: Optional[str] = None,
        verbose: bool = False,
        vsrc_callback: Optional[Callable[[float, str], float]] = None,
        data_callback: Optional[Callable[[float, Dict[str, float]], None]] = None
    ):
        self.verbose = verbose
        self.output_logs: List[str] = []
        self.user_vsrc_callback = vsrc_callback
        self.user_data_callback = data_callback
        self.progress_callback: Optional[Callable[[float, int], None]] = None
        self.timestep_count = 0
        self._stop_requested = False
        
        resolved, tried = resolve_ngspice_library(dll_path)
        if resolved is None:
            raise FileNotFoundError(
                "ngspice library not found. Tried:\n  "
                + "\n  ".join(tried) + _MISSING_DLL_HELP)

        self.dll_path = resolved
        self._load_dll()
        self._init_ngspice()

    def _load_dll(self):
        # find_library() can return a bare soname ("libngspice.so.0") with no
        # directory part. Only touch PATH/add_dll_directory for real file
        # paths, otherwise we would prepend the current directory to PATH.
        if os.path.dirname(self.dll_path):
            dll_dir = os.path.dirname(os.path.abspath(self.dll_path))
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(dll_dir)
                except Exception:
                    pass
            if dll_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')

        self.lib = ctypes.CDLL(self.dll_path)

        self.lib.ngSpice_Init.argtypes = [
            SendChar_t, SendStat_t, ControlledExit_t,
            SendData_t, SendInitData_t, BGThreadRunning_t, ctypes.c_void_p
        ]
        self.lib.ngSpice_Init.restype = ctypes.c_int

        self.lib.ngSpice_Init_Sync.argtypes = [
            GetVSRCData_t, GetISRCData_t, GetSyncData_t, ctypes.POINTER(ctypes.c_int), ctypes.c_void_p
        ]
        self.lib.ngSpice_Init_Sync.restype = ctypes.c_int

        self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
        self.lib.ngSpice_Command.restype = ctypes.c_int

        self.lib.ngSpice_Circ.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        self.lib.ngSpice_Circ.restype = ctypes.c_int

        self.lib.ngSpice_CurPlot.argtypes = []
        self.lib.ngSpice_CurPlot.restype = ctypes.c_char_p

        self.lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]
        self.lib.ngGet_Vec_Info.restype = ctypes.POINTER(VectorInfo)

        self.lib.ngSpice_running.argtypes = []
        self.lib.ngSpice_running.restype = ctypes.c_bool

    def _cb_send_char(self, output: bytes, id_: int, user_data: Any) -> int:
        msg = output.decode('utf-8', errors='replace') if output else ""
        self.output_logs.append(msg)
        if self.verbose:
            print(f"[ngspice] {msg}", end="")
        return 0

    def _cb_send_stat(self, status: bytes, id_: int, user_data: Any) -> int:
        if self.verbose and status:
            print(f"[ngspice stat] {status.decode('utf-8', errors='replace')}")
        return 0

    def _cb_exit(self, status: int, immediate: bool, quit_exit: bool, id_: int, user_data: Any) -> int:
        if self.verbose:
            print(f"[ngspice exit] status={status}")
        return 0

    def _cb_send_data(self, p_data: Any, count: int, id_: int, user_data: Any) -> int:
        if not p_data or not self.user_data_callback:
            return 0
        try:
            data = p_data.contents
            time_val = 0.0
            vec_dict = {}
            for i in range(data.veccount):
                v_ptr = data.vecsa[i]
                if v_ptr:
                    v = v_ptr.contents
                    name = v.name.decode('utf-8', errors='replace') if v.name else ""
                    if v.is_scale:
                        time_val = v.creal
                    else:
                        vec_dict[name] = v.creal
            self.user_data_callback(time_val, vec_dict)
        except Exception as e:
            if self.verbose:
                print(f"[send_data error] {e}")
        return 0

    def _cb_get_vsrc(self, v_ret: Any, actual_time: float, node_name: bytes, id_: int, user_data: Any) -> int:
        if self.user_vsrc_callback and v_ret:
            name_str = node_name.decode('utf-8', errors='replace') if node_name else ""
            v_val = self.user_vsrc_callback(actual_time, name_str)
            v_ret[0] = float(v_val)
        return 0

    def _cb_sync(self, actual_time: float, p_delta_t: Any, old_delta_t: float,
                 redostep: int, ident: int, location: int, user_data: Any) -> int:
        """
        Per-timestep hook (ngspice's GetSyncData): drives the progress bar and
        the abort check.

        Returning 1 from a sync callback is what makes ngspice abort the run,
        so the UI never has to wait for the full duration to honour a Stop.
        """
        self.timestep_count = getattr(self, "timestep_count", 0) + 1
        if self.progress_callback is not None:
            try:
                self.progress_callback(float(actual_time), self.timestep_count)
            except Exception:
                pass
        # Deliberately does NOT abort here. Returning non-zero from this
        # callback wedges ngspice in this build; request_stop() interrupts from
        # a separate thread instead.
        return 0

    def _init_ngspice(self):
        # Keep references to ctypes callback instances to prevent garbage collection
        self._c_send_char = SendChar_t(self._cb_send_char)
        self._c_send_stat = SendStat_t(self._cb_send_stat)
        self._c_exit = ControlledExit_t(self._cb_exit)
        self._c_send_data = SendData_t(self._cb_send_data)
        self._c_send_init_data = SendInitData_t(lambda d, i, u: 0)
        self._c_bg_running = BGThreadRunning_t(lambda r, i, u: 0)

        self._c_get_vsrc = GetVSRCData_t(self._cb_get_vsrc)
        self._c_get_isrc = GetISRCData_t(lambda v, t, n, i, u: 0)
        self._c_get_sync = GetSyncData_t(self._cb_sync)

        ret = self.lib.ngSpice_Init(
            self._c_send_char,
            self._c_send_stat,
            self._c_exit,
            self._c_send_data,
            self._c_send_init_data,
            self._c_bg_running,
            None
        )
        if ret != 0:
            raise RuntimeError(f"ngSpice_Init failed with code {ret}")

        ident = ctypes.c_int(0)
        self.lib.ngSpice_Init_Sync(
            self._c_get_vsrc,
            self._c_get_isrc,
            self._c_get_sync,
            ctypes.byref(ident),
            None
        )

    def request_stop(self):
        """
        Interrupt a running simulation.

        Issues ngspice's `stop` command from a short-lived thread. It has to be
        another thread: the solver is inside ngSpice_Command("run"), so the
        thread that started it is blocked and cannot send the command itself.
        Issuing `stop` from inside the sync callback instead re-enters ngspice
        and deadlocks this build.
        """
        self._stop_requested = True

        def _issue():
            try:
                self.cmd("stop")
            except Exception:
                pass

        try:
            t = threading.Thread(target=_issue, daemon=True)
            t.start()
            return True
        except Exception:
            return False

    @property
    def stop_requested(self) -> bool:
        return bool(getattr(self, "_stop_requested", False))

    def set_vsrc_callback(self, callback: Callable[[float, str], float]):
        """Register dynamic voltage source callback for `external` sources."""
        self.user_vsrc_callback = callback

    def set_data_callback(self, callback: Callable[[float, Dict[str, float]], None]):
        """Register per-timestep vector data callback."""
        self.user_data_callback = callback

    def cmd(self, command: str) -> int:
        return self.lib.ngSpice_Command(command.encode('utf-8'))

    def load_circuit(self, netlist_lines: List[str]):
        lines = [line.strip() for line in netlist_lines if line.strip()]
        # ngspice treats the FIRST line of a deck as its title and drops it
        # from the circuit. A netlist that starts with a device line ("V1 in 0
        # ...") therefore loses its source: the remaining nodes float, the DC
        # operating point reports "singular matrix", and ngSpice_Command("run")
        # wedges forever inside gmin/source stepping. Every netlist this app
        # generates already begins with a `*` comment; hand-typed ones (Netlist
        # Editor, tests) may not, so guarantee a title line here.
        if not lines or not lines[0].startswith("*"):
            lines.insert(0, "* WOWKISPICE circuit")
        if not any(l.lower() == ".end" for l in lines):
            lines.append(".end")

        c_array = (ctypes.c_char_p * (len(lines) + 1))()
        for idx, line in enumerate(lines):
            c_array[idx] = line.encode('utf-8')
        c_array[len(lines)] = None

        ret = self.lib.ngSpice_Circ(c_array)
        if ret != 0:
            raise RuntimeError(f"ngSpice_Circ failed to load circuit (code {ret})")

    def load_circuit_file(self, filepath: str):
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.load_circuit(lines)

    def alter_source_voltage(self, source_name: str, voltage: float):
        self.cmd(f"alter {source_name} = {voltage}")

    def get_node_voltage(self, node_name: str) -> float:
        vec_ptr = self.lib.ngGet_Vec_Info(node_name.encode('utf-8'))
        if not vec_ptr:
            vec_ptr = self.lib.ngGet_Vec_Info(f"v({node_name})".encode('utf-8'))
            
        if not vec_ptr:
            raise ValueError(f"Vector '{node_name}' not found in current ngspice plot.")
        
        vec = vec_ptr.contents
        if vec.v_length <= 0 or not vec.v_realdata:
            return 0.0
        return float(vec.v_realdata[vec.v_length - 1])

    def get_vector_complex(self, vec_name: str) -> Tuple[List[float], List[float]]:
        """
        (real, imaginary) parts of a vector.

        An .ac sweep produces complex phasors; taking only the real part - as
        get_vector_array() does - would quietly discard the phase information a
        Bode plot is made of.
        """
        vec_ptr = self.lib.ngGet_Vec_Info(vec_name.encode('utf-8'))
        if not vec_ptr:
            vec_ptr = self.lib.ngGet_Vec_Info(f"v({vec_name})".encode('utf-8'))
        if not vec_ptr:
            return [], []
        vec = vec_ptr.contents
        if vec.v_length <= 0:
            return [], []

        class NgComplex(ctypes.Structure):
            _fields_ = [("cx_r", ctypes.c_double), ("cx_i", ctypes.c_double)]

        if vec.v_compdata:
            c_arr = ctypes.cast(vec.v_compdata, ctypes.POINTER(NgComplex))
            return ([float(c_arr[i].cx_r) for i in range(vec.v_length)],
                    [float(c_arr[i].cx_i) for i in range(vec.v_length)])
        if vec.v_realdata:
            reals = [float(vec.v_realdata[i]) for i in range(vec.v_length)]
            return reals, [0.0] * len(reals)
        return [], []

    def get_vector_array(self, vec_name: str) -> List[float]:
        vec_ptr = self.lib.ngGet_Vec_Info(vec_name.encode('utf-8'))
        if not vec_ptr:
            vec_ptr = self.lib.ngGet_Vec_Info(f"v({vec_name})".encode('utf-8'))
        if not vec_ptr:
            return []
        vec = vec_ptr.contents
        if vec.v_length <= 0:
            return []
        if bool(vec.v_realdata):
            return [float(vec.v_realdata[i]) for i in range(vec.v_length)]
        elif bool(vec.v_compdata):
            class NgComplex(ctypes.Structure):
                _fields_ = [("cx_r", ctypes.c_double), ("cx_i", ctypes.c_double)]
            c_arr = ctypes.cast(vec.v_compdata, ctypes.POINTER(NgComplex))
            return [float(c_arr[i].cx_r) for i in range(vec.v_length)]
        return []
