#ifndef SPICE_BACKEND_H
#define SPICE_BACKEND_H

#include <QString>
#include <QVector>
#include <QMap>
#include <functional>
#include <memory>

#ifdef _WIN32
#include <windows.h>
#endif

/// C-compatible ABI signatures matching wowkispice_ffi.dll extern "C" functions
typedef void* (*wowkispice_ffi_new_t)();
typedef void  (*wowkispice_ffi_destroy_t)(void*);
typedef int   (*wowkispice_ffi_init_t)(void*);
typedef int   (*wowkispice_ffi_cmd_t)(void*, const char*);
typedef int   (*wowkispice_ffi_load_circuit_t)(void*, const char* const*, int);
typedef const char* (*wowkispice_ffi_cur_plot_t)(void*);
typedef int   (*wowkispice_ffi_reset_t)(void*);
typedef int   (*wowkispice_ffi_get_vector_array_t)(void*, const char*, double*, int*);
typedef double (*wowkispice_ffi_get_last_sample_t)(void*, const char*);

/// Wrapper around wowkispice_ffi.dll so the Qt GUI can run ngspice simulations.
/// Loads the DLL at runtime via LoadLibrary/GetProcAddress (Windows).
class SpiceBackend {
public:
    SpiceBackend();
    ~SpiceBackend();

    bool isAvailable() const { return m_dll != nullptr; }
    QString errorString() const { return m_error; }

    /// Create a new ngspice engine instance. Returns false on failure.
    bool createEngine();
    void destroyEngine();

    /// Initialize ngspice with default (no-op) callbacks.
    bool init();
    /// Execute an ngspice command string (e.g. "run", "alter V1 = 5", ".tran 1u 10m").
    bool cmd(const QString &command);
    /// Load a circuit deck (list of netlist lines) into ngspice.
    bool loadCircuit(const QStringList &lines);
    /// Get the current plot name.
    QString curPlot() const;
    /// Reset ngspice.
    bool reset();
    /// Get a real vector as QVector<double>. Returns false if vector not found.
    bool getVectorArray(const QString &vecName, QVector<double> &out) const;
    /// Get the last sample of a real vector.
    double getLastSample(const QString &vecName) const;

private:
    bool loadDll();
    void unloadDll();
    bool resolveSymbols();

#ifdef _WIN32
    HMODULE m_dll = nullptr;
#else
    void *m_dll = nullptr;
#endif
    void *m_engine = nullptr;
    mutable QString m_error;

    // Resolved function pointers
    wowkispice_ffi_new_t          m_fn_new = nullptr;
    wowkispice_ffi_destroy_t      m_fn_destroy = nullptr;
    wowkispice_ffi_init_t         m_fn_init = nullptr;
    wowkispice_ffi_cmd_t          m_fn_cmd = nullptr;
    wowkispice_ffi_load_circuit_t m_fn_load_circuit = nullptr;
    wowkispice_ffi_cur_plot_t     m_fn_cur_plot = nullptr;
    wowkispice_ffi_reset_t        m_fn_reset = nullptr;
    wowkispice_ffi_get_vector_array_t m_fn_get_vector_array = nullptr;
    wowkispice_ffi_get_last_sample_t  m_fn_get_last_sample = nullptr;
};

#endif // SPICE_BACKEND_H
