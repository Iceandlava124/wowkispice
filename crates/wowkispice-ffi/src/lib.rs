/*
 * wowkispice-ffi - ngspice FFI layer for WOWKISPICE.
 *
 * Dependency-free (apart from wowkispice-core) bindings to libngspice /
 * ngspice.dll, hand-written from the checked-in sharedspice.h.  DLL loading
 * and symbol resolution are done at runtime with raw OS FFI
 * (LoadLibrary/GetProcAddress on Windows, dlopen/dlsym on Linux) so no
 * `libloading` or `libc` crate is needed, and no ngspice.lib is required at
 * link time.
 *
 * All ngspice function symbols are resolved lazily on first use.  Callback
 * trampolines bridge ngspice's C function-pointer callbacks to Rust closures
 * stored in the userdata pointer.
 */

#![allow(non_camel_case_types, dead_code, unused_unsafe)]

use std::ffi::{c_void, CStr, CString};
use std::fmt;
use std::os::raw::{c_char, c_double, c_int, c_short, c_uchar};
use std::ptr;
use std::sync::Mutex;
use wowkispice_core::ngspice_wrapper::{NgSpiceError, NgSpiceResult};

// ngspice keeps process-global state; tests that drive it must not overlap.
#[cfg(test)]
pub(crate) static NGSPICE_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

// ---------------------------------------------------------------------------
// DLL loading (raw OS FFI, no external crates)
// ---------------------------------------------------------------------------

#[cfg(target_os = "windows")]
mod dll_os {
    use super::*;

    #[link(name = "kernel32")]
    extern "system" {
        pub fn LoadLibraryExA(
            lpFileName: *const c_char,
            hFile: *mut c_void,
            dwFlags: c_int,
        ) -> *mut c_void;
        pub fn GetProcAddress(
            hModule: *mut c_void,
            lpProcName: *const c_char,
        ) -> *mut c_void;
        pub fn FreeLibrary(hModule: *mut c_void) -> c_int;
        pub fn GetLastError() -> u32;
    }

    // Search the DLL's own directory for its dependencies. Python's ctypes
    // loads with this flag; plain LoadLibraryExA(..., 0) fails with error 126
    // because ngspice.dll's sibling DLLs are not on PATH.
    const LOAD_WITH_ALTERED_SEARCH_PATH: c_int = 0x0000_0008;

    pub(crate) type DllHandle = *mut c_void;

    pub(crate) unsafe fn dll_load(path: &str) -> Result<DllHandle, String> {
        let c_path = CString::new(path).map_err(|e| e.to_string())?;
        let handle = LoadLibraryExA(
            c_path.as_ptr(),
            ptr::null_mut(),
            LOAD_WITH_ALTERED_SEARCH_PATH,
        );
        if handle.is_null() {
            let err = GetLastError();
            Err(format!("LoadLibraryExA failed for {} (error {})", path, err))
        } else {
            Ok(handle)
        }
    }

    pub(crate) unsafe fn dll_sym(handle: DllHandle, name: &str) -> Result<*mut c_void, String> {
        let c_name = CString::new(name).map_err(|e| e.to_string())?;
        let sym = GetProcAddress(handle, c_name.as_ptr());
        if sym.is_null() {
            Err(format!("GetProcAddress failed for {}", name))
        } else {
            Ok(sym)
        }
    }

    pub(crate) unsafe fn dll_unload(handle: DllHandle) {
        if !handle.is_null() {
            FreeLibrary(handle);
        }
    }
}

#[cfg(target_os = "linux")]
mod dll_os {
    use super::*;

    #[link(name = "dl")]
    extern "C" {
        pub fn dlopen(filename: *const c_char, flag: c_int) -> *mut c_void;
        pub fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
        pub fn dlclose(handle: *mut c_void) -> c_int;
    }

    pub(crate) type DllHandle = *mut c_void;

    const RTLD_NOW: c_int = 2;

    pub(crate) unsafe fn dll_load(path: &str) -> Result<DllHandle, String> {
        let c_path = CString::new(path).map_err(|e| e.to_string())?;
        let handle = dlopen(c_path.as_ptr(), RTLD_NOW);
        if handle.is_null() {
            Err(format!("dlopen failed for {}", path))
        } else {
            Ok(handle)
        }
    }

    pub(crate) unsafe fn dll_sym(handle: DllHandle, name: &str) -> Result<*mut c_void, String> {
        let c_name = CString::new(name).map_err(|e| e.to_string())?;
        let sym = dlsym(handle, c_name.as_ptr());
        if sym.is_null() {
            Err(format!("dlsym failed for {}", name))
        } else {
            Ok(sym)
        }
    }

    pub(crate) unsafe fn dll_unload(handle: DllHandle) {
        if !handle.is_null() {
            dlclose(handle);
        }
    }
}

use dll_os::{dll_load, DllHandle};

// ---------------------------------------------------------------------------
// C types from sharedspice.h
// ---------------------------------------------------------------------------

/// Complex number type from ngspice.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct NgComplex {
    pub cx_real: c_double,
    pub cx_imag: c_double,
}

/// Vector info obtained from ngspice.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct NgVectorInfo {
    pub v_name: *mut c_char,
    pub v_type: c_int,
    pub v_flags: c_short,
    pub v_realdata: *mut c_double,
    pub v_compdata: *mut NgComplex,
    pub v_length: c_int,
}

/// Vector value entry.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct NgVecValues {
    pub name: *mut c_char,
    pub creal: c_double,
    pub cimag: c_double,
    pub is_scale: c_uchar,
    pub is_complex: c_uchar,
}

/// All vector values for a plot.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct NgVecValuesAll {
    pub veccount: c_int,
    pub vecindex: c_int,
    pub vecsa: *mut *mut NgVecValues,
}

/// Vector info entry.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct NgVecInfo {
    pub number: c_int,
    pub vecname: *mut c_char,
    pub is_real: c_uchar,
    pub pdvec: *mut c_void,
    pub pdvecscale: *mut c_void,
}

/// All vector info for a plot.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct NgVecInfoAll {
    pub name: *mut c_char,
    pub title: *mut c_char,
    pub date: *mut c_char,
    pub r#type: *mut c_char,
    pub veccount: c_int,
    pub vecs: *mut *mut NgVecInfo,
}

// ---------------------------------------------------------------------------
// Callback types from sharedspice.h
// ---------------------------------------------------------------------------

pub type SendChar_t =
    extern "C" fn(*mut c_char, c_int, *mut c_void) -> c_int;
pub type SendStat_t =
    extern "C" fn(*mut c_char, c_int, *mut c_void) -> c_int;
pub type ControlledExit_t =
    extern "C" fn(c_int, c_uchar, c_uchar, c_int, *mut c_void) -> c_int;
pub type SendData_t =
    extern "C" fn(*mut NgVecValuesAll, c_int, c_int, *mut c_void) -> c_int;
pub type SendInitData_t =
    extern "C" fn(*mut NgVecInfoAll, c_int, *mut c_void) -> c_int;
pub type BGThreadRunning_t =
    extern "C" fn(c_uchar, c_int, *mut c_void) -> c_int;

pub type GetVSRCData_t =
    extern "C" fn(*mut c_double, c_double, *mut c_char, c_int, *mut c_void)
        -> c_int;
pub type GetISRCData_t =
    extern "C" fn(*mut c_double, c_double, *mut c_char, c_int, *mut c_void)
        -> c_int;
pub type GetSyncData_t =
    extern "C" fn(c_double, *mut c_double, c_double, c_int, c_int, c_int, *mut c_void)
        -> c_int;

// ---------------------------------------------------------------------------
// Resolved ngspice function pointers (resolved at runtime via dll_sym)
// ---------------------------------------------------------------------------

pub type NgSpiceInitFn =
    extern "C" fn(SendChar_t, SendStat_t, ControlledExit_t, SendData_t,
                  SendInitData_t, BGThreadRunning_t, *mut c_void) -> c_int;
pub type NgSpiceInitSyncFn =
    extern "C" fn(GetVSRCData_t, GetISRCData_t, GetSyncData_t, *mut c_int,
                  *mut c_void) -> c_int;
pub type NgSpiceCommandFn = extern "C" fn(*mut c_char) -> c_int;
pub type NgGetVecInfoFn = extern "C" fn(*mut c_char) -> *mut NgVectorInfo;
pub type NgSpiceCircFn = extern "C" fn(*mut *mut c_char) -> c_int;
pub type NgSpiceCurPlotFn = extern "C" fn() -> *mut c_char;
pub type NgSpiceAllPlotsFn = extern "C" fn() -> *mut *mut c_char;
pub type NgSpiceAllVecsFn = extern "C" fn(*mut c_char) -> *mut *mut c_char;
pub type NgSpiceRunningFn = extern "C" fn() -> c_uchar;
pub type NgSpiceSetBkptFn = extern "C" fn(c_double) -> c_uchar;
pub type NgSpiceNoSPIInitFn = extern "C" fn() -> c_int;
pub type NgSpiceNoSpiceInitFn = extern "C" fn() -> c_int;
pub type NgSpiceLockReallocFn = extern "C" fn() -> c_int;
pub type NgSpiceUnlockReallocFn = extern "C" fn() -> c_int;
pub type NgSpiceResetFn = extern "C" fn() -> c_int;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// FFI-specific errors.
#[derive(Debug)]
pub enum FfiError {
    DllLoad(String),
    DllSymbol(String),
    Nul(std::ffi::NulError),
    NullPointer(String),
    SymbolNotResolved(String),
}

impl fmt::Display for FfiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FfiError::DllLoad(s) => write!(f, "DLL load failed: {s}"),
            FfiError::DllSymbol(s) => write!(f, "DLL symbol missing: {s}"),
            FfiError::Nul(e) => write!(f, "NUL error: {e}"),
            FfiError::NullPointer(s) => write!(f, "null pointer: {s}"),
            FfiError::SymbolNotResolved(s) => write!(f, "symbol not resolved: {s}"),
        }
    }
}

impl std::error::Error for FfiError {}

impl From<std::ffi::NulError> for FfiError {
    fn from(e: std::ffi::NulError) -> Self {
        FfiError::Nul(e)
    }
}

impl From<FfiError> for NgSpiceError {
    fn from(e: FfiError) -> Self {
        match e {
            FfiError::DllLoad(_) => NgSpiceError::DllNotLoaded,
            FfiError::DllSymbol(s) => {
                NgSpiceError::AnalysisFailed(format!("DLL symbol not resolved: {s}"))
            }
            FfiError::Nul(e) => NgSpiceError::NulError(e),
            FfiError::NullPointer(s) => NgSpiceError::AnalysisFailed(s),
            FfiError::SymbolNotResolved(s) => NgSpiceError::AnalysisFailed(s),
        }
    }
}

pub type FfiResult<T> = Result<T, FfiError>;

// ---------------------------------------------------------------------------
// Helper: resolve a symbol and transmute to the desired function type
// ---------------------------------------------------------------------------

macro_rules! resolve_fn {
    ($handle:expr, $name:literal, $t:ty) => {{
        let sym = unsafe { dll_os::dll_sym($handle, $name) }
            .map_err(|e| FfiError::DllSymbol(format!("{}: {}", $name, e)))?;
        unsafe { std::mem::transmute::<*mut c_void, $t>(sym) }
    }};
}

// ---------------------------------------------------------------------------
// Callback userdata bridge
// ---------------------------------------------------------------------------

/// Userdata boxed and passed to ngspice as `void*`.
struct CallbackUserdata {
    vsrc: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
    data: Option<Box<dyn Fn(f64, Vec<(String, f64)>) + Send + Sync>>,
    progress: Option<Box<dyn Fn(f64, usize) + Send + Sync>>,
    /// Sync callback: (time, old_delta, redostep, id, location) -> i32
    sync: Option<Box<Mutex<Box<dyn FnMut(f64, f64, i32, i32, i32) -> i32 + Send>>>>,
}

fn box_userdata(
    vsrc: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
    data: Option<Box<dyn Fn(f64, Vec<(String, f64)>) + Send + Sync>>,
    progress: Option<Box<dyn Fn(f64, usize) + Send + Sync>>,
    sync: Option<Box<dyn FnMut(f64, f64, i32, i32, i32) -> i32 + Send>>,
) -> *mut c_void {
    Box::into_raw(Box::new(CallbackUserdata {
        vsrc,
        data,
        progress,
        sync: sync.map(|s| Box::new(Mutex::new(s))),
    })) as *mut c_void
}

fn unbox_userdata<'a>(ptr: *mut c_void) -> Option<&'a CallbackUserdata> {
    if ptr.is_null() {
        None
    } else {
        Some(unsafe { &*(ptr as *const CallbackUserdata) })
    }
}

fn take_userdata(ptr: *mut c_void) -> Option<Box<CallbackUserdata>> {
    if ptr.is_null() {
        None
    } else {
        Some(unsafe { Box::from_raw(ptr as *mut CallbackUserdata) })
    }
}

// ---------------------------------------------------------------------------
// Callback trampolines
// ---------------------------------------------------------------------------

extern "C" fn sendchar_trampoline(
    _buf: *mut c_char,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    0
}

extern "C" fn sendstat_trampoline(
    _buf: *mut c_char,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    0
}

extern "C" fn controlled_exit_trampoline(
    _status: c_int,
    _immediate: c_uchar,
    _quit: c_uchar,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    0
}

extern "C" fn senddata_trampoline(
    _values: *mut NgVecValuesAll,
    _count: c_int,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    0
}

extern "C" fn sendinitdata_trampoline(
    _info: *mut NgVecInfoAll,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    0
}

extern "C" fn bgthreadrunning_trampoline(
    _running: c_uchar,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    0
}

extern "C" fn getvsrcdata_trampoline(
    ret: *mut c_double,
    time: c_double,
    name: *mut c_char,
    _id: c_int,
    userdata: *mut c_void,
) -> c_int {
    let ud = match unbox_userdata(userdata) {
        Some(u) => u,
        None => return -1,
    };
    let Some(ref vsrc_cb) = ud.vsrc else { return -1 };

    let node = unsafe { CStr::from_ptr(name) }.to_string_lossy().to_string();
    let value = vsrc_cb(time, &node);
    unsafe {
        *ret = value;
    }
    0
}

extern "C" fn getisrcdata_trampoline(
    _ret: *mut c_double,
    _time: c_double,
    _name: *mut c_char,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    -1
}

extern "C" fn getsyncdata_trampoline(
    time: c_double,
    _delta: *mut c_double,
    olddelta: c_double,
    redostep: c_int,
    id: c_int,
    location: c_int,
    userdata: *mut c_void,
) -> c_int {
    let ud = match unbox_userdata(userdata) {
        Some(u) => u,
        None => return -1,
    };
    let Some(ref sync_cb) = ud.sync else { return -1 };
    let mut cb = sync_cb.lock().unwrap();
    cb(time, olddelta, redostep, id, location)
}

// ---------------------------------------------------------------------------
// NgSpiceFfi - high-level FFI wrapper
// ---------------------------------------------------------------------------

/// High-level interface to libngspice / ngspice.dll backed by the real DLL.
///
/// All symbols are resolved at runtime via `dll_sym`; no link-time
/// dependency on ngspice.lib is required.
pub struct NgSpiceFfi {
    dll: DllHandle,
    /// Resolved function pointers.
    init: Option<NgSpiceInitFn>,
    init_sync: Option<NgSpiceInitSyncFn>,
    command: Option<NgSpiceCommandFn>,
    get_vec_info: Option<NgGetVecInfoFn>,
    get_vsrc_data: Option<GetVSRCData_t>,
    circ: Option<NgSpiceCircFn>,
    cur_plot: Option<NgSpiceCurPlotFn>,
    all_plots: Option<NgSpiceAllPlotsFn>,
    all_vecs: Option<NgSpiceAllVecsFn>,
    running: Option<NgSpiceRunningFn>,
    set_bkpt: Option<NgSpiceSetBkptFn>,
    nospinit: Option<NgSpiceNoSPIInitFn>,
    nospiceinit: Option<NgSpiceNoSpiceInitFn>,
    lock_realloc: Option<NgSpiceLockReallocFn>,
    unlock_realloc: Option<NgSpiceUnlockReallocFn>,
    reset: Option<NgSpiceResetFn>,
    userdata: *mut c_void,
    /// Whether ngSpice_Init has been called successfully.
    initialized: bool,
}

impl NgSpiceFfi {
    /// Load the ngspice library and resolve all symbols.
    ///
    /// Uses the same resolution order as
    /// `wowkispice-core::ngspice_wrapper::resolve_ngspice_library`.
    /// `ngSpice_Init` is NOT called here - call `init()` separately after
    /// setting up callbacks.
    pub fn new() -> NgSpiceResult<Self> {
        let (dll_path, _tried) =
            wowkispice_core::ngspice_wrapper::resolve_ngspice_library(None);
        let dll_path = match dll_path {
            Some(p) => p,
            None => return Err(NgSpiceError::DllNotLoaded),
        };

        unsafe {
            let handle = dll_load(&dll_path).map_err(|e| {
                NgSpiceError::AnalysisFailed(format!("DLL load failed: {e}"))
            })?;

            // Resolve all required symbols
            let init = resolve_fn!(handle, "ngSpice_Init", NgSpiceInitFn);
            let init_sync =
                resolve_fn!(handle, "ngSpice_Init_Sync", NgSpiceInitSyncFn);
            let command =
                resolve_fn!(handle, "ngSpice_Command", NgSpiceCommandFn);
            let get_vec_info =
                resolve_fn!(handle, "ngGet_Vec_Info", NgGetVecInfoFn);
            // Not every ngspice build exports this; the field is Option and
            // callers already treat it as optional.
            let get_vsrc_data: Option<GetVSRCData_t> =
                dll_os::dll_sym(handle, "ngGetVSRCData").ok().map(|sym| unsafe {
                    std::mem::transmute::<*mut c_void, GetVSRCData_t>(sym)
                });
            let circ =
                resolve_fn!(handle, "ngSpice_Circ", NgSpiceCircFn);
            let cur_plot =
                resolve_fn!(handle, "ngSpice_CurPlot", NgSpiceCurPlotFn);
            let all_plots =
                resolve_fn!(handle, "ngSpice_AllPlots", NgSpiceAllPlotsFn);
            let all_vecs =
                resolve_fn!(handle, "ngSpice_AllVecs", NgSpiceAllVecsFn);
            let running =
                resolve_fn!(handle, "ngSpice_running", NgSpiceRunningFn);
            let set_bkpt =
                resolve_fn!(handle, "ngSpice_SetBkpt", NgSpiceSetBkptFn);
            let nospinit =
                resolve_fn!(handle, "ngSpice_nospinit", NgSpiceNoSPIInitFn);
            let nospiceinit =
                resolve_fn!(handle, "ngSpice_nospiceinit", NgSpiceNoSpiceInitFn);
            let lock_realloc =
                resolve_fn!(handle, "ngSpice_LockRealloc",
                    NgSpiceLockReallocFn);
            let unlock_realloc =
                resolve_fn!(handle, "ngSpice_UnlockRealloc",
                    NgSpiceUnlockReallocFn);
            let reset_fn =
                resolve_fn!(handle, "ngSpice_Reset", NgSpiceResetFn);

            Ok(Self {
                dll: handle,
                init: Some(init),
                init_sync: Some(init_sync),
                command: Some(command),
                get_vec_info: Some(get_vec_info),
                get_vsrc_data,
                circ: Some(circ),
                cur_plot: Some(cur_plot),
                all_plots: Some(all_plots),
                all_vecs: Some(all_vecs),
                running: Some(running),
                set_bkpt: Some(set_bkpt),
                nospinit: Some(nospinit),
                nospiceinit: Some(nospiceinit),
                lock_realloc: Some(lock_realloc),
                unlock_realloc: Some(unlock_realloc),
                reset: Some(reset_fn),
                userdata: ptr::null_mut(),
                initialized: false,
            })
        }
    }

    /// Initialize ngspice with the given callbacks.
    ///
    /// Boxes the closures into userdata and passes the raw pointer to
    /// `ngSpice_Init`.
    pub fn init(
        &mut self,
        vsrc: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
        data: Option<Box<dyn Fn(f64, Vec<(String, f64)>) + Send + Sync>>,
        progress: Option<Box<dyn Fn(f64, usize) + Send + Sync>>,
        sync: Option<Box<dyn FnMut(f64, f64, i32, i32, i32) -> i32 + Send>>,
    ) -> NgSpiceResult<()> {
        let Some(init) = self.init else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_Init not resolved".to_string(),
            ));
        };

        let ud = box_userdata(vsrc, data, progress, sync);
        self.userdata = ud;

        let rc = init(
            sendchar_trampoline,
            sendstat_trampoline,
            controlled_exit_trampoline,
            senddata_trampoline,
            sendinitdata_trampoline,
            bgthreadrunning_trampoline,
            ud,
        );
        if rc != 0 {
            // ngSpice_Init failed - clean up userdata
            take_userdata(ud);
            self.userdata = ptr::null_mut();
            return Err(NgSpiceError::AnalysisFailed(format!(
                "ngSpice_Init returned {rc}"
            )));
        }
        self.initialized = true;
        Ok(())
    }

    /// Execute an ngspice command string.
    pub fn cmd(&mut self, command: &str) -> NgSpiceResult<c_int> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(command_fn) = self.command else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_Command not resolved".to_string(),
            ));
        };
        let c_cmd = CString::new(command).map_err(NgSpiceError::NulError)?;
        let rc = unsafe { command_fn(c_cmd.as_ptr() as *mut c_char) };
        if rc != 0 {
            return Err(NgSpiceError::AnalysisFailed(format!(
                "ngSpice_Command returned {rc}"
            )));
        }
        Ok(rc)
    }

    /// Load a circuit deck into ngspice.
    ///
    /// The deck is passed as a null-terminated array of C strings to
    /// `ngSpice_Circ`.
    pub fn load_circuit(&mut self, lines: &[&str]) -> NgSpiceResult<()> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(circ) = self.circ else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_Circ".to_string(),
            ));
        };

        // Build the null-terminated array of C strings.
        let mut c_strings: Vec<CString> = lines
            .iter()
            .map(|line| CString::new(*line).map_err(NgSpiceError::NulError))
            .collect::<Result<Vec<CString>, _>>()?;
        c_strings.push(CString::new("").unwrap()); // NULL terminator

        let mut ptrs: Vec<*mut c_char> =
            c_strings.iter().map(|s| s.as_ptr() as *mut c_char).collect();
        ptrs.push(ptr::null_mut());

        let rc = unsafe { circ(ptrs.as_mut_ptr()) };
        if rc != 0 {
            return Err(NgSpiceError::AnalysisFailed(format!(
                "ngSpice_Circ returned {rc}"
            )));
        }
        Ok(())
    }

    /// Get the current plot name.
    pub fn cur_plot(&self) -> NgSpiceResult<String> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(cur_plot) = self.cur_plot else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_CurPlot".to_string(),
            ));
        };
        let ptr = unsafe { cur_plot() };
        if ptr.is_null() {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_CurPlot returned null".to_string(),
            ));
        }
        Ok(unsafe { CStr::from_ptr(ptr) }.to_string_lossy().to_string())
    }

    /// Get all plot names.
    pub fn all_plots(&self) -> NgSpiceResult<Vec<String>> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(all_plots) = self.all_plots else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_AllPlots".to_string(),
            ));
        };
        let ptr = unsafe { all_plots() };
        if ptr.is_null() {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_AllPlots returned null".to_string(),
            ));
        }
        let mut plots = Vec::new();
        let mut i = 0;
        loop {
            let name_ptr = unsafe { *ptr.add(i) };
            if name_ptr.is_null() {
                break;
            }
            plots.push(unsafe {
                CStr::from_ptr(name_ptr).to_string_lossy().to_string()
            });
            i += 1;
        }
        Ok(plots)
    }

    /// Reset ngspice.
    pub fn reset(&mut self) -> NgSpiceResult<c_int> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(reset_fn) = self.reset else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngSpice_Reset".to_string(),
            ));
        };
        let rc = unsafe { reset_fn() };
        Ok(rc)
    }

    /// Get a real vector as a list of f64 values.
    pub fn get_vector_array(&self, vec_name: &str) -> NgSpiceResult<Vec<f64>> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(get_vec_info) = self.get_vec_info else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngGet_Vec_Info".to_string(),
            ));
        };
        let c_name = CString::new(vec_name).map_err(NgSpiceError::NulError)?;
        let info = unsafe { get_vec_info(c_name.as_ptr() as *mut c_char) };
        if info.is_null() {
            return Err(NgSpiceError::AnalysisFailed(format!(
                "vector {vec_name} not found"
            )));
        }
        let info = unsafe { &*info };
        let mut out = Vec::with_capacity(info.v_length as usize);
        for i in 0..info.v_length as usize {
            out.push(unsafe { *info.v_realdata.add(i) });
        }
        Ok(out)
    }

    /// Get a vector as (real, imaginary) parts.
    pub fn get_vector_complex(
        &self,
        vec_name: &str,
    ) -> NgSpiceResult<(Vec<f64>, Vec<f64>)> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(get_vec_info) = self.get_vec_info else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngGet_Vec_Info".to_string(),
            ));
        };
        let c_name = CString::new(vec_name).map_err(NgSpiceError::NulError)?;
        let info = unsafe { get_vec_info(c_name.as_ptr() as *mut c_char) };
        if info.is_null() {
            return Err(NgSpiceError::AnalysisFailed(format!(
                "vector {vec_name} not found"
            )));
        }
        let info = unsafe { &*info };
        let mut real = Vec::with_capacity(info.v_length as usize);
        let mut imag = Vec::with_capacity(info.v_length as usize);
        for i in 0..info.v_length as usize {
            real.push(unsafe { *info.v_realdata.add(i) });
            imag.push(unsafe { info.v_compdata.add(i).read().cx_imag });
        }
        Ok((real, imag))
    }

    /// Alter a source voltage via the `alter` command.
    pub fn alter_source_voltage(
        &mut self,
        source_name: &str,
        voltage: f64,
    ) -> NgSpiceResult<()> {
        self.cmd(&format!("alter {source_name} = {voltage}"))?;
        Ok(())
    }

    /// Get the last sample of a real vector.
    ///
    /// Efficient for callbacks - returns just the last value instead of
    /// copying the entire vector.
    pub fn get_last_sample(&self, vec_name: &str) -> NgSpiceResult<f64> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let Some(get_vec_info) = self.get_vec_info else {
            return Err(NgSpiceError::AnalysisFailed(
                "ngGet_Vec_Info".to_string(),
            ));
        };
        let c_name = CString::new(vec_name).map_err(NgSpiceError::NulError)?;
        let info = unsafe { get_vec_info(c_name.as_ptr() as *mut c_char) };
        if info.is_null() {
            return Err(NgSpiceError::AnalysisFailed(format!(
                "vector {vec_name} not found"
            )));
        }
        let info = unsafe { &*info };
        if info.v_length <= 0 || info.v_realdata.is_null() {
            return Ok(0.0);
        }
        Ok(unsafe { *info.v_realdata.add(info.v_length as usize - 1) })
    }

    /// Return the raw `ngSpice_CurPlot` function pointer for use in callbacks.
    pub fn cur_plot_method(&self) -> Option<NgSpiceCurPlotFn> {
        self.cur_plot
    }

    /// Return the raw `ngGet_Vec_Info` function pointer for use in callbacks.
    ///
    /// Callbacks fire during `cmd("run")`, when `&self` is mutably borrowed.
    /// Callers should call this method *before* `cmd()` to obtain the function
    /// pointer, then call it directly from within the callback without going
    /// through `&self` again.
    pub fn get_vec_info_fn(&self) -> Option<NgGetVecInfoFn> {
        self.get_vec_info
    }

    /// Return the raw `ngSpice_Init_Sync` function pointer for use in
    /// callbacks.
    ///
    /// Callbacks fire during `cmd("run")`, when `&self` is mutably borrowed.
    /// Callers should call this method *before* `cmd()` to obtain the function
    /// pointer, then call it directly from within the callback without going
    /// through `&self` again.
    pub fn ngspice_init_sync_fn(&self) -> Option<NgSpiceInitSyncFn> {
        self.init_sync
    }
}

impl Drop for NgSpiceFfi {
    fn drop(&mut self) {
        if !self.userdata.is_null() {
            take_userdata(self.userdata);
        }
        // Don't unload the DLL - ngspice may have allocated memory that
        // the OS will clean up on process exit. Freeing the DLL while
        // ngspice state is still live causes heap corruption.
    }
}

// ---------------------------------------------------------------------------
// C-compatible API for GUI interop
// ---------------------------------------------------------------------------

/// Opaque handle to an NgSpiceFfi instance.
/// Created with `wowkispice_ffi_new`, destroyed with `wowkispice_ffi_destroy`.
#[repr(C)]
pub struct FfiHandle {
    _opaque: [u8; 0],
}

/// Create a new NgSpiceFfi instance.
/// Returns a null pointer on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_new() -> *mut FfiHandle {
    match NgSpiceFfi::new() {
        Ok(engine) => Box::into_raw(Box::new(engine)) as *mut FfiHandle,
        Err(_) => ptr::null_mut(),
    }
}

/// Destroy an NgSpiceFfi instance created with `wowkispice_ffi_new`.
/// Safe to call with a null pointer.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_destroy(ptr: *mut FfiHandle) {
    if !ptr.is_null() {
        unsafe {
            let _ = Box::from_raw(ptr as *mut NgSpiceFfi);
        }
    }
}

/// Initialize ngspice with default (no-op) callbacks.
/// Returns 0 on success, non-zero on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_init(ptr: *mut FfiHandle) -> c_int {
    if ptr.is_null() {
        return -1;
    }
    let engine = unsafe { &mut *(ptr as *mut NgSpiceFfi) };
    match engine.init(None, None, None, None) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Execute an ngspice command string.
/// Returns 0 on success, non-zero on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_cmd(ptr: *mut FfiHandle, command: *const c_char) -> c_int {
    if ptr.is_null() || command.is_null() {
        return -1;
    }
    let engine = unsafe { &mut *(ptr as *mut NgSpiceFfi) };
    let c_str = unsafe { CStr::from_ptr(command) };
    match engine.cmd(c_str.to_string_lossy().as_ref()) {
        Ok(_) => 0,
        Err(_) => -1,
    }
}

/// Load a circuit deck into ngspice.
/// `lines` is an array of `count` null-terminated C strings.
/// Returns 0 on success, non-zero on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_load_circuit(
    ptr: *mut FfiHandle,
    lines: *const *const c_char,
    count: c_int,
) -> c_int {
    if ptr.is_null() || lines.is_null() || count <= 0 {
        return -1;
    }
    let engine = unsafe { &mut *(ptr as *mut NgSpiceFfi) };

    let mut rust_lines: Vec<&str> = Vec::with_capacity(count as usize);
    for i in 0..count as usize {
        let line_ptr = unsafe { *lines.add(i) };
        if line_ptr.is_null() {
            return -1;
        }
        match unsafe { CStr::from_ptr(line_ptr).to_str() } {
            Ok(s) => rust_lines.push(s),
            Err(_) => return -1,
        }
    }

    match engine.load_circuit(&rust_lines) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Get the current plot name.
/// Returns a pointer to a null-terminated string owned by ngspice (do not free),
/// or null on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_cur_plot(ptr: *mut FfiHandle) -> *const c_char {
    if ptr.is_null() {
        return ptr::null();
    }
    let engine = unsafe { &*(ptr as *mut NgSpiceFfi) };
    match engine.cur_plot() {
        Ok(_name) => {
            // Return the raw pointer from ngspice's own memory (like ngSpice_CurPlot does)
            // We need to call the underlying function directly since engine.cur_plot()
            // converts to a Rust String. Use the function pointer instead.
            let Some(cur_plot_fn) = engine.cur_plot_method() else {
                return ptr::null();
            };
            let ptr = unsafe { cur_plot_fn() };
            ptr as *const c_char
        }
        Err(_) => ptr::null(),
    }
}

/// Reset ngspice.
/// Returns 0 on success, non-zero on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_reset(ptr: *mut FfiHandle) -> c_int {
    if ptr.is_null() {
        return -1;
    }
    let engine = unsafe { &mut *(ptr as *mut NgSpiceFfi) };
    match engine.reset() {
        Ok(_) => 0,
        Err(_) => -1,
    }
}

/// Get a real vector as an array of f64 values.
/// `out` must point to a buffer that can hold at least `*out_len` values.
/// On return, `*out_len` is set to the actual number of values written.
/// Returns 0 on success, non-zero on failure.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_get_vector_array(
    ptr: *mut FfiHandle,
    vec_name: *const c_char,
    out: *mut c_double,
    out_len: *mut c_int,
) -> c_int {
    if ptr.is_null() || vec_name.is_null() || out.is_null() || out_len.is_null() {
        return -1;
    }
    let engine = unsafe { &*(ptr as *mut NgSpiceFfi) };
    let c_str = unsafe { CStr::from_ptr(vec_name) };
    match engine.get_vector_array(c_str.to_string_lossy().as_ref()) {
        Ok(values) => {
            let len = values.len() as c_int;
            unsafe { *out_len = len };
            for i in 0..values.len() {
                unsafe { *out.add(i) = values[i] };
            }
            0
        }
        Err(_) => -1,
    }
}

/// Get the last sample of a real vector.
/// Returns 0.0 on failure or if vector is empty.
#[no_mangle]
pub extern "C" fn wowkispice_ffi_get_last_sample(
    ptr: *mut FfiHandle,
    vec_name: *const c_char,
) -> c_double {
    if ptr.is_null() || vec_name.is_null() {
        return 0.0;
    }
    let engine = unsafe { &*(ptr as *mut NgSpiceFfi) };
    let c_str = unsafe { CStr::from_ptr(vec_name) };
    match engine.get_last_sample(c_str.to_string_lossy().as_ref()) {
        Ok(v) => v,
        Err(_) => 0.0,
    }
}

// ---------------------------------------------------------------------------
// cosim_runner module
// ---------------------------------------------------------------------------

pub mod cosim_runner;
pub mod mock_controller;
pub mod studio_engine;
pub use cosim_runner::*;

// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ffi_module_compiles() {
        assert!(true);
    }

    #[test]
    fn test_ffi_loads_dll_and_resolves_symbols() {
        let _guard = crate::NGSPICE_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        // This test verifies the ngspice DLL loads and all symbols resolve.
        match NgSpiceFfi::new() {
            Ok(engine) => {
                // Verify all function pointers are resolved
                assert!(engine.init.is_some());
                assert!(engine.init_sync.is_some());
                assert!(engine.command.is_some());
                assert!(engine.get_vec_info.is_some());
                assert!(engine.circ.is_some());
                assert!(engine.cur_plot.is_some());
                assert!(engine.all_plots.is_some());
                assert!(engine.all_vecs.is_some());
                assert!(engine.running.is_some());
                assert!(engine.set_bkpt.is_some());
                assert!(engine.nospinit.is_some());
                assert!(engine.nospiceinit.is_some());
                assert!(engine.lock_realloc.is_some());
                assert!(engine.unlock_realloc.is_some());
                assert!(engine.reset.is_some());
            }
            Err(e) => panic!("ngspice DLL load failed: {e}"),
        }
    }

    #[test]
    fn test_ffi_end_to_end_run_rc_circuit() {
        let _guard = crate::NGSPICE_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        // End-to-end smoke test: load a simple RC circuit, run it,
        // and read back the output voltage.
        let mut engine = match NgSpiceFfi::new() {
            Ok(e) => e,
            Err(e) => panic!("ngspice DLL load failed: {e}"),
        };

        // ngSpice_Init requires callbacks; pass no-op closures.
        engine.init(None, None, None, None).expect("ngSpice_Init should succeed");

        // Load a simple RC circuit: 1V step into 1k resistor + 1uF cap
        let deck: &[&str] = &[
            "* RC step response test",
            "V1 in 0 PWL(0 0 1n 1)",
            "R1 in out 1k",
            "C1 out 0 1u IC=0",
            ".tran 1u 10m uic",
            ".end",
        ];
        engine.load_circuit(deck).expect("ngSpice_Circ should succeed");

        // Run the simulation
        engine.cmd("run").expect("ngSpice_Command 'run' should succeed");

        // Read back the time and output vectors
        let time = engine
            .get_vector_array("time")
            .expect("get_vector_array('time') should succeed");
        let vout = engine
            .get_vector_array("v(out)")
            .expect("get_vector_array('v(out)') should succeed");

        // Verify we got data
        assert!(!time.is_empty(), "time vector should not be empty");
        assert!(!vout.is_empty(), "v(out) vector should not be empty");
        assert_eq!(
            time.len(),
            vout.len(),
            "time and v(out) should have same length"
        );

        // Final output should be close to 1V (step response settles)
        let final_vout = *vout.last().unwrap();
        assert!(
            final_vout > 0.9 && final_vout <= 1.0,
            "final v(out) should be ~1.0V, got {final_vout}"
        );
    }
}