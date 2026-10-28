"""ngspice ctypes wrapper for PROJECT_WOWKISPICE

Provides high-level Python interface to libngspice / ngspice.dll with native
high-speed synchronization callbacks (GetVSRCData, GetSyncData, SendData).
"""

import ctypes
import ctypes.util
import os
import re
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
                "ngspice library not found. Tried:\n  " +
                "\n  ".join(tried) + _MISSING_DLL_HELP)

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
        """Per-timestep hook (ngspice's GetSyncData): drives the progress bar and
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
        """Interrupt a running simulation.

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
        return self.lib.ngSpice_Command(
            self.validate_cmd(command).encode('utf-8'))

    # ------------------------------------------------------------------
    # JOB 4: ngspice input sanitiser — single choke point
    # ------------------------------------------------------------------

    # Directive allowlist (case-insensitive, default: no path traversal)
    # These dot-directives are allowed in untrusted netlists:
    ALLOWED_DIRECTIVES = frozenset({
        'tran', 'ac', 'dc', 'op', 'ic', 'nodeset',
        'step', 'options', 'param', 'model', 'subckt',
        'ends', 'measure', 'meas', 'print', 'save', 'temp', 'end',
        # Analysis cards real callers send: .noise (thermal-noise yield),
        # .disto (harmonic distortion). Both are pure analysis directives -
        # no file access, no command execution - so they are safe to allow.
        'noise', 'disto',
        # .include/.lib/.inc are listed here only so the blanket ban does not
        # fire: _sanitise_line then checks the target path against
        # ALLOWED_INCLUDE_DIRS and rejects anything outside it.
        'include', 'lib', 'inc',
    })

    # J4: directory allowlist for .include / .lib / .inc targets.
    # Policy default: nothing outside these directories is ever allowed.
    # The entries below are exactly the library paths the real tests load
    # (tests/test_components_library.py:16 and :34 -> circuits/components/models.lib).
    # PROJECT_ROOT is anchored at THIS FILE's location (bridge/.. = repo root),
    # never at the process working directory, so decisions do not move with cwd.
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ALLOWED_INCLUDE_DIRS = frozenset({
        os.path.join(PROJECT_ROOT, 'circuits', 'components'),
    })

    # Maximum nesting depth when scanning included files (3b finding: a
    # .control block inside an allowed included file executed for real, so the
    # scan is recursive with this cap; a self-including cycle trips it).
    INCLUDE_SCAN_DEPTH_LIMIT = 5

    # Matches an include-family directive plus its file argument, quoted or bare.
    # The argument is optional in the pattern so that a bare `.include` still
    # matches and can be rejected for having no file argument.
    INCLUDE_ARG_RE = re.compile(
        r'^[ \t]*\.([a-zA-Z]+)(?:[ \t]+(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?',
        re.IGNORECASE)

    # Legitimate cmd() commands that the code sends through ngSpice_Command.
    # Enumerated by grepping every `.cmd(` call site under bridge/, ui/, tests/
    # and tools/ (job R4-01): run x36, setplot x6, stop x1, alter x1, plus the
    # transient-card form `tran ...` (bridge/mock_controller.py:156) and the
    # alter form built in bridge/load_stepper.py:31. Nothing else is sent.
    Cmd_ALLOWED = frozenset({
        'run', 'bg_run', 'reset', 'destroy',
        'alter', 'stop', 'setplot', 'tran',
    })

    # Characters that let one string carry a second command or a redirection.
    # `cmd("shell echo PWNED> <marker>")` (SECURITY.md vector 2) is exactly
    # this shape, so the guard rejects them before ngspice ever parses.
    CMD_FORBIDDEN_CHARS = re.compile(r'[\r\n;|&`$<>]')

    # Regex: match a dot-directive at line-start (case-insensitive, optional
    # leading whitespace/tabs, CRLF-safe after normalisation)
    DOT_DIR_RE = re.compile(r'^[ \t]*\.([a-zA-Z]+)\s', re.IGNORECASE)

    # --------------------------------------------------------------
    # Internal helpers
    # --------------------------------------------------------------

    @staticmethod
    def _strip_normalize(line: str) -> str:
        """Remove leading whitespace/tabs, normalise CRLF, handle '+' continuations."""
        # Normalise CRLF → LF
        line = line.replace('\r\n', '\n').replace('\r', '\n')
        # Strip leading whitespace and tabs
        line = line.lstrip(' \t')
        # '+' continuation: if the remaining text starts with '+', strip it
        if line.startswith('+'):
            line = line[1:].lstrip(' \t')
        return line

    @staticmethod
    def _is_banned_directive(norm: str) -> Tuple[bool, Optional[str]]:
        """Return (banned, directive_name) after checking norm against allowlist."""
        # First, check for explicitly banned directives that might have no trailing whitespace
        norm_lower = norm.lower().strip()
        if norm_lower in {'.control', '.endc'}:
            name = norm_lower.lstrip('.').strip()
            return True, name
        # Then, regex-based check for dot-directives with trailing whitespace
        m = NgSpiceEngine.DOT_DIR_RE.match(norm)
        if m:
            directive = m.group(1).lower()
            if directive in NgSpiceEngine.ALLOWED_DIRECTIVES:
                return False, None
            return True, directive
        # Not a dot-directive, not banned
        return False, None

    @staticmethod
    def _is_banned_cmd(norm: str) -> Tuple[bool, Optional[str]]:
        """Return (banned, cmd_name) after checking norm against cmd allowlist."""
        # norm is already stripped and lowercased by the caller
        if norm not in NgSpiceEngine.Cmd_ALLOWED:
            parts = norm.split()
            cmd_name = parts[0] if parts else ''
            return True, cmd_name
        return False, None

    @staticmethod
    def validate_cmd(command: str) -> str:
        """Return `command` if it is an allowed ngspice command, else raise.

        `cmd()` is the second path into ngspice's command language: it hands
        its string straight to `ngSpice_Command`, so the netlist sanitiser
        does not protect it. Measured before this guard existed (SECURITY.md
        vector 2, logs/activity.jsonl job S3A-EXPLOIT):
        `cmd("shell echo PWNED> <marker>")` created the marker file on both
        HEAD and the sanitiser draft.

        Rules, in order: the verb (first token) must be in Cmd_ALLOWED; the
        whole string must then be free of control and redirection characters.
        Rejection is a RuntimeError naming the verb so the caller can tell a
        policy refusal from a simulator error.
        """
        if not isinstance(command, str):
            raise TypeError(
                "ngSpice_Command rejected: command must be str, got %r"
                % (type(command).__name__,)
            )
        text = command.strip()
        if not text:
            raise RuntimeError("ngSpice_Command rejected: empty command")
        # Verb first: for `shell ...` the actionable reason is the verb, not
        # the redirection character that happens to follow it.
        verb = text.split()[0].lower()
        if verb not in NgSpiceEngine.Cmd_ALLOWED:
            raise RuntimeError(
                "ngSpice_Command rejected the command "
                "(not on allowlist: %r) @cmd: %s" % (verb, text)
            )
        offending = NgSpiceEngine.CMD_FORBIDDEN_CHARS.search(text)
        if offending:
            raise RuntimeError(
                "ngSpice_Command rejected the command "
                "(character %r not permitted) @cmd: %s"
                % (offending.group(0), text)
            )
        return text

    @staticmethod
    def _check_include_path(raw: str, directive: str, depth: int = 0
                            ) -> str:
        """Validate a .include/.lib/.inc target and scan its content.

        A relative argument is tried both against the process cwd and against
        the repo root; a candidate INSIDE the allowlist is preferred over one
        outside it, so a foreign cwd with a look-alike path cannot win. The
        matched candidate is realpath'd before the comparison, so '..' and
        symlinks collapse first and cannot escape the allowlist.

        Returns the validated absolute path, which _sanitise_line rewrites
        into the netlist line: ngspice then reads exactly the file that was
        validated, regardless of where the process was started (3c).

        The file's OWN lines are scanned with the same sanitiser rules,
        recursively up to INCLUDE_SCAN_DEPTH_LIMIT - a .control block inside
        an allowed library executed for real (3b), so checking only the
        top-level netlist was not enough. Depth >= limit raises (cycle cap).
        """
        if not raw:
            raise RuntimeError(
                f"ngSpice_Circ rejected the untrusted netlist: "
                f".{directive} with no file argument @line"
            )
        if depth >= NgSpiceEngine.INCLUDE_SCAN_DEPTH_LIMIT:
            raise RuntimeError(
                f"ngSpice_Circ rejected the untrusted netlist: "
                f".{directive} nesting exceeds depth "
                f"{NgSpiceEngine.INCLUDE_SCAN_DEPTH_LIMIT} @line: {raw}"
            )
        candidates = []
        if os.path.isabs(raw):
            candidates.append(raw)
        else:
            candidates.append(os.path.join(os.getcwd(), raw))
            candidates.append(os.path.join(NgSpiceEngine.PROJECT_ROOT, raw))
        allowed = [os.path.realpath(d) for d in NgSpiceEngine.ALLOWED_INCLUDE_DIRS]
        inside: List[str] = []
        for cand in candidates:
            resolved = os.path.realpath(cand)
            for d in allowed:
                if resolved == d or resolved.startswith(d + os.sep):
                    inside.append(resolved)
                    break
        # Prefer an allowlisted candidate that exists as a file; if one
        # resolved inside the allowlist but cannot be read, say so rather
        # than falling through to the outside error (clearer and fail-closed).
        for resolved in inside:
            if os.path.isfile(resolved):
                NgSpiceEngine._scan_included_file(resolved, depth + 1)
                return resolved
        if inside:
            raise RuntimeError(
                f"ngSpice_Circ rejected the untrusted netlist: "
                f".{directive} file not found or unreadable @line: {inside[0]}"
            )
        raise RuntimeError(
            f"ngSpice_Circ rejected the untrusted netlist: "
            f".{directive} outside allowed directories @line: {raw}"
        )

    @staticmethod
    def _scan_included_file(path: str, depth: int) -> None:
        """Apply the same line rules to every line of an included file.

        Reads the file (already validated as inside ALLOWED_INCLUDE_DIRS),
        runs _sanitise_line over each line with the recursion depth for any
        nested include, and re-raises rejections with the file path so the
        error names where the banned content lives.
        """
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                content = fh.read()
        except OSError as exc:
            raise RuntimeError(
                f"ngSpice_Circ rejected the untrusted netlist: "
                f"included file unreadable: {path} ({exc})"
            ) from exc
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                NgSpiceEngine._sanitise_line(line, depth=depth)
            except RuntimeError as exc:
                raise RuntimeError(
                    f"ngSpice_Circ rejected the untrusted netlist: "
                    f"{path}: {exc}"
                ) from exc

    @staticmethod
    def _sanitise_line(line: str, depth: int = 0) -> str:
        """Process a single netlist line through the sanitiser.

        Raises RuntimeError with a specific message if the line contains a
        banned directive or command. Returns the normalised line if safe.
        """
        norm = NgSpiceEngine._strip_normalize(line)

        # Skip blank lines and comment lines (starting with *); they pass through
        if not norm or norm.startswith('*'):
            return norm

        # Check for banned dot-directives
        banned, directive = NgSpiceEngine._is_banned_directive(norm)
        if banned:
            raise RuntimeError(
                f"ngSpice_Circ rejected the untrusted netlist: "
                f"banned directive @line: .{directive}"
            )

        # .include / .lib / .inc: pass the allowlist only after the file
        # argument resolves inside ALLOWED_INCLUDE_DIRS (default: nowhere else),
        # its content passes the same rules (recursive, depth-capped), and the
        # line is rewritten to the validated absolute path (3c: ngspice then
        # reads exactly what was checked, whatever the cwd).
        inc_m = NgSpiceEngine.INCLUDE_ARG_RE.match(norm)
        if inc_m and inc_m.group(1).lower() in ('include', 'lib', 'inc'):
            raw = inc_m.group(2) or inc_m.group(3) or inc_m.group(4) or ''
            resolved = NgSpiceEngine._check_include_path(
                raw, inc_m.group(1).lower(), depth=depth)
            grp = (2 if inc_m.group(2) is not None else
                   3 if inc_m.group(3) is not None else 4)
            gs, ge = inc_m.span(grp)
            replacement = resolved if grp != 4 or ' ' not in resolved \
                else f'"{resolved}"'
            norm = norm[:gs] + replacement + norm[ge:]

        # Check for banned cmd() references in netlist content.
        # Legitimate code sends: run, bg_run, reset, destroy, alter.
        # Look for 'cmd(' pattern (case-insensitive) in the normalised line.
        if 'cmd(' in norm.lower() or 'Cmd(' in norm:
            # Extract potential command name
            banned_cmd, cmd_name = NgSpiceEngine._is_banned_cmd(norm)
            if banned_cmd:
                raise RuntimeError(
                    f"ngSpice_Circ rejected the untrusted netlist: "
                    f"banned command in netlist @line"
                )

        # Re-check after normalization (in case '+' continuation changed things)
        norm = NgSpiceEngine._strip_normalize(norm)
        banned, directive = NgSpiceEngine._is_banned_directive(norm)
        if banned:
            raise RuntimeError(
                f"ngSpice_Circ rejected the untrusted netlist: "
                f"banned directive @line: .{directive}"
            )

        return norm

    def load_circuit(self, netlist_lines: List[str]):
        """Load a netlist into ngspice with input sanitisation.

        Sanitises the netlist before passing it to ngSpice_Circ, rejecting
        untrusted directives, file-output commands, and shell commands.

        Only element lines, comments, blank lines, and the dot-directives
        .tran .ac .dc .op .ic .nodeset .step .options .param .model .subckt .ends
        .measure (.meas alias) .print .save(memory only) .temp .end are allowed,
        plus .include/.lib/.inc only when the file argument resolves inside
        ALLOWED_INCLUDE_DIRS (default: no directory outside that set), the
        included file's own lines pass these same rules (recursive scan,
        depth limit INCLUDE_SCAN_DEPTH_LIMIT), and the line is rewritten to
        the validated absolute path.

        cmd() allowlist: run, bg_run, reset, destroy, alter, stop, setplot, tran
        (the commands the legitimate code sends), enforced by validate_cmd()
        inside cmd() itself - not only by this netlist path. Reject with a
        clear, specific error naming the directive
        and line: .control/.endc, any shell/system/exec-style command,
        write/wrdata/hardcopy/any file-output command, .include/.lib/.inc/source
        outside an allowed directory (default: none), and any unknown
        dot-directive.

        Citations: ngspice manual section for the installed version (UNVERIFIED)
        if no manual available.
        """
        # Strip, normalise, and validate every line before passing to ngspice
        sanitised: List[str] = []
        for idx, line in enumerate(netlist_lines):
            # Skip completely empty lines (they are implicit)
            if not line.strip():
                continue
            try:
                sline = NgSpiceEngine._sanitise_line(line)
            except RuntimeError as exc:
                # Re-raise with line context
                raise RuntimeError(
                    f"ngSpice_Circ rejected the untrusted netlist: "
                    f"{exc}"
                ) from exc
            sanitised.append(sline)

        # Ensure the netlist has a title comment and .end marker
        if not sanitised or not sanitised[0].startswith("*"):
            sanitised.insert(0, "* WOWKISPICE circuit")
        if not any(l.lower() == ".end" for l in sanitised):
            sanitised.append(".end")

        c_array = (ctypes.c_char_p * (len(sanitised) + 1))()
        for idx, line in enumerate(sanitised):
            c_array[idx] = line.encode('utf-8')
        c_array[len(sanitised)] = None

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
        """(real, imaginary) parts of a vector.

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