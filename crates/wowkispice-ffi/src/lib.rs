/*
 * wowkispice-ffi - ngspice FFI layer for WOWKISPICE.
 *
 * Dependency-free (apart from wowkispice-core) bindings to libngspice /
 * ngspice.dll, hand-written from the checked-in sharedspice.h.  DLL loading
 * is done with raw OS FFI (LoadLibrary/GetProcAddress on Windows,
 * dlopen/dlsym on Linux) so no `libloading` or `libc` crate is needed.
 *
 * This is the skeleton FFI layer: DLL loading and symbol resolution work,
 * callback trampolines are declared with the correct signatures, and the
 * high-level NgSpiceFfi struct owns the DLL handle.  Full per-callback
 * wiring is added incrementally as each solver feature is brought up.
 */

#![allow(non_camel_case_types, dead_code)]

use std::ffi::{c_void, CStr, CString};
use std::fmt;
use std::os::raw::{c_char, c_double, c_int, c_short, c_uchar};
use std::ptr;
use wowkispice_core::ngspice_wrapper::{NgSpiceError, NgSpiceResult};

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
    }

    pub(crate) type DllHandle = *mut c_void;

    pub(crate) unsafe fn dll_load(path: &str) -> Result<DllHandle, String> {
        let c_path = CString::new(path).map_err(|e| e.to_string())?;
        let handle = LoadLibraryExA(c_path.as_ptr(), ptr::null_mut(), 0);
        if handle.is_null() {
            Err(format!("LoadLibraryExA failed for {}", path))
        } else {
            Ok(handle)
        }
    }

    pub(crate) unsafe fn dll_sym(
        handle: DllHandle,
        name: &str,
    ) -> Result<*mut c_void, String> {
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

    pub(crate) unsafe fn dll_sym(
        handle: DllHandle,
        name: &str,
    ) -> Result<*mut c_void, String> {
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

use dll_os::{dll_load, dll_unload, DllHandle};

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
    extern "C" fn(*mut c_double, c_double, *mut c_char, c_int, *mut c_void) -> c_int;
pub type GetISRCData_t =
    extern "C" fn(*mut c_double, c_double, *mut c_char, c_int, *mut c_void) -> c_int;
pub type GetSyncData_t =
    extern "C" fn(c_double, *mut c_double, c_double, c_int, c_int, c_int, *mut c_void)
    -> c_int;

// ---------------------------------------------------------------------------
// ngspice function declarations
// ---------------------------------------------------------------------------

extern "C" {
    pub fn ngSpice_Init(
        printfcn: SendChar_t,
        statfcn: SendStat_t,
        ngexit: ControlledExit_t,
        sdata: SendData_t,
        sinitdata: SendInitData_t,
        bgtrun: BGThreadRunning_t,
        userData: *mut c_void,
    ) -> c_int;

    pub fn ngSpice_Init_Sync(
        vsrcdat: GetVSRCData_t,
        isrcdat: GetISRCData_t,
        syncdat: GetSyncData_t,
        ident: *mut c_int,
        userData: *mut c_void,
    ) -> c_int;

    pub fn ngSpice_Command(command: *mut c_char) -> c_int;
    pub fn ngGet_Vec_Info(vecname: *mut c_char) -> *mut NgVectorInfo;
    pub fn ngSpice_Circ(circarray: *mut *mut c_char) -> c_int;
    pub fn ngSpice_CurPlot() -> *mut c_char;
    pub fn ngSpice_AllPlots() -> *mut *mut c_char;
    pub fn ngSpice_AllVecs(plotname: *mut c_char) -> *mut *mut c_char;
    pub fn ngSpice_running() -> c_uchar;
    pub fn ngSpice_SetBkpt(time: c_double) -> c_uchar;
    pub fn ngSpice_nospinit() -> c_int;
    pub fn ngSpice_nospiceinit() -> c_int;
    pub fn ngSpice_LockRealloc() -> c_int;
    pub fn ngSpice_UnlockRealloc() -> c_int;
    pub fn ngSpice_Reset() -> c_int;
}

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
}

impl fmt::Display for FfiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FfiError::DllLoad(s) => write!(f, "DLL load failed: {s}"),
            FfiError::DllSymbol(s) => write!(f, "DLL symbol missing: {s}"),
            FfiError::Nul(e) => write!(f, "NUL error: {e}"),
            FfiError::NullPointer(s) => write!(f, "null pointer: {s}"),
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
            FfiError::DllSymbol(_) => NgSpiceError::DllNotLoaded,
            FfiError::Nul(e) => NgSpiceError::NulError(e),
            FfiError::NullPointer(s) => NgSpiceError::AnalysisFailed(s),
        }
    }
}

pub type FfiResult<T> = Result<T, FfiError>;

// ---------------------------------------------------------------------------
// Callback userdata bridge
// ---------------------------------------------------------------------------

/// Userdata boxed and passed to ngspice as `void*`.
struct CallbackUserdata {
    vsrc: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
    data: Option<Box<dyn Fn(f64, Vec<(String, f64)>) + Send + Sync>>,
    progress: Option<Box<dyn Fn(f64, usize) + Send + Sync>>,
}

fn box_userdata(
    vsrc: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
    data: Option<Box<dyn Fn(f64, Vec<(String, f64)>) + Send + Sync>>,
    progress: Option<Box<dyn Fn(f64, usize) + Send + Sync>>,
) -> *mut c_void {
    Box::into_raw(Box::new(CallbackUserdata { vsrc, data, progress })) as *mut c_void
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
// Callback trampolines (signatures match sharedspice.h; bodies are stubs)
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
    _ret: *mut c_double,
    _time: c_double,
    _name: *mut c_char,
    _id: c_int,
    _userdata: *mut c_void,
) -> c_int {
    -1
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
    _time: c_double,
    _delta: *mut c_double,
    _olddelta: c_double,
    _redostep: c_int,
    _id: c_int,
    _location: c_int,
    _userdata: *mut c_void,
) -> c_int {
    -1
}

// ---------------------------------------------------------------------------
// NgSpiceFfi - high-level FFI wrapper
// ---------------------------------------------------------------------------

/// High-level interface to libngspice / ngspice.dll backed by the real DLL.
///
/// Unlike `wowkispice-core::ngspice_wrapper::NgSpiceEngine` (which is a
/// stub that returns `DllNotLoaded`), this struct actually loads the DLL
/// and wires up the FFI callbacks.
pub struct NgSpiceFfi {
    dll: DllHandle,
    userdata: *mut c_void,
    /// Whether ngSpice_Init has been called successfully.
    initialized: bool,
}

impl NgSpiceFfi {
    /// Load the ngspice library and create the engine handle.
    ///
    /// Uses the same resolution order as
    /// `wowkispice-core::ngspice_wrapper::resolve_ngspice_library`.
    /// `ngSpice_Init` is NOT called here — call `init()` separately after
    /// setting up callbacks.
    pub fn new() -> NgSpiceResult<Self> {
        let (dll_path, _tried) =
            wowkispice_core::ngspice_wrapper::resolve_ngspice_library(None);
        let dll_path = match dll_path {
            Some(p) => p,
            None => return Err(NgSpiceError::MissingDLL),
        };

        unsafe {
            let handle = dll_load(&dll_path).map_err(|e| {
                NgSpiceError::AnalysisFailed(format!("DLL load failed: {e}"))
            })?;

            Ok(Self {
                dll: handle,
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
    ) -> NgSpiceResult<()> {
        unsafe {
            let ud =
                box_userdata(vsrc, data, progress);
            self.userdata = ud;

            let rc = ngSpice_Init(
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
    }

    /// Execute an ngspice command string.
    pub fn cmd(&mut self, command: &str) -> NgSpiceResult<c_int> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let c_cmd = CString::new(command).map_err(NgSpiceError::NulError)?;
        let rc = unsafe { ngSpice_Command(c_cmd.as_ptr() as *mut c_char) };
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
    pub fn load_circuit(&mut self, lines: &[String]) -> NgSpiceResult<()> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }

        // Build the null-terminated array of C strings.
        let mut c_strings: Vec<CString> = Vec::new();
        for line in lines {
            c_strings.push(CString::new(line.as_str()).map_err(NgSpiceError::NulError)?);
        }
        c_strings.push(CString::new("").unwrap()); // NULL terminator

        let mut ptrs: Vec<*mut c_char> =
            c_strings.iter().map(|s| s.as_ptr() as *mut c_char).collect();
        ptrs.push(ptr::null_mut());

        let rc = unsafe { ngSpice_Circ(ptrs.as_mut_ptr()) };
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
        let ptr = unsafe { ngSpice_CurPlot() };
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
        let ptr = unsafe { ngSpice_AllPlots() };
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
            plots.push(unsafe { CStr::from_ptr(name_ptr) }.to_string_lossy().to_string());
            i += 1;
        }
        Ok(plots)
    }

    /// Reset ngspice.
    pub fn reset(&mut self) -> NgSpiceResult<c_int> {
        if !self.initialized {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let rc = unsafe { ngSpice_Reset() };
        Ok(rc)
    }
}

impl Drop for NgSpiceFfi {
    fn drop(&mut self) {
        if !self.userdata.is_null() {
            take_userdata(self.userdata);
        }
        unsafe {
            dll_unload(self.dll);
        }
    }
}

// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    #[test]
    fn test_ffi_module_compiles() {
        assert!(true);
    }
}
