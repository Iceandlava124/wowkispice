#include "spice_backend.h"

#include <QDir>
#include <QCoreApplication>
#include <QDebug>

#ifdef _WIN32
#define LOAD_DLL(path) LoadLibraryA(path)
#define GET_PROC(handle, name) GetProcAddress(handle, name)
#define FREE_DLL(handle) FreeLibrary(handle)
#else
#define LOAD_DLL(path) dlopen(path, RTLD_NOW)
#define GET_PROC(handle, name) dlsym(handle, name)
#define FREE_DLL(handle) dlclose(handle)
#endif

SpiceBackend::SpiceBackend()
{
    loadDll();
}

SpiceBackend::~SpiceBackend()
{
    destroyEngine();
    unloadDll();
}

bool SpiceBackend::loadDll()
{
    // Search for wowkispice_ffi.dll next to the executable and in the project dir
    QStringList searchPaths;
#ifdef _WIN32
    searchPaths << QCoreApplication::applicationDirPath()
                << QDir::currentPath()
                << QString("%1/../installer").arg(QCoreApplication::applicationDirPath());
#else
    searchPaths << QCoreApplication::applicationDirPath()
                << QDir::currentPath();
#endif

    QString dllName = "wowkispice_ffi.dll";

    for (const QString &dir : searchPaths) {
        QString path = dir + QDir::separator() + dllName;
        if (QFile::exists(path)) {
#ifdef _WIN32
            m_dll = LOAD_DLL(path.toLocal8Bit().constData());
#else
            m_dll = LOAD_DLL(path.toLocal8Bit().constData());
#endif
            if (m_dll) {
                return resolveSymbols();
            }
        }
    }

    m_error = QString("wowkispice_ffi.dll not found in any search path");
    return false;
}

void SpiceBackend::unloadDll()
{
    if (m_dll) {
        FREE_DLL(m_dll);
        m_dll = nullptr;
    }
    m_fn_new = nullptr;
    m_fn_destroy = nullptr;
    m_fn_init = nullptr;
    m_fn_cmd = nullptr;
    m_fn_load_circuit = nullptr;
    m_fn_cur_plot = nullptr;
    m_fn_reset = nullptr;
    m_fn_get_vector_array = nullptr;
    m_fn_get_last_sample = nullptr;
}

bool SpiceBackend::resolveSymbols()
{
    m_fn_new = reinterpret_cast<wowkispice_ffi_new_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_new")));
    m_fn_destroy = reinterpret_cast<wowkispice_ffi_destroy_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_destroy")));
    m_fn_init = reinterpret_cast<wowkispice_ffi_init_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_init")));
    m_fn_cmd = reinterpret_cast<wowkispice_ffi_cmd_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_cmd")));
    m_fn_load_circuit = reinterpret_cast<wowkispice_ffi_load_circuit_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_load_circuit")));
    m_fn_cur_plot = reinterpret_cast<wowkispice_ffi_cur_plot_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_cur_plot")));
    m_fn_reset = reinterpret_cast<wowkispice_ffi_reset_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_reset")));
    m_fn_get_vector_array = reinterpret_cast<wowkispice_ffi_get_vector_array_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_get_vector_array")));
    m_fn_get_last_sample = reinterpret_cast<wowkispice_ffi_get_last_sample_t>(
        reinterpret_cast<void*>(GET_PROC(m_dll, "wowkispice_ffi_get_last_sample")));

    if (!m_fn_new || !m_fn_destroy || !m_fn_init || !m_fn_cmd ||
        !m_fn_load_circuit || !m_fn_cur_plot || !m_fn_reset ||
        !m_fn_get_vector_array || !m_fn_get_last_sample) {
        m_error = "Failed to resolve one or more symbols in wowkispice_ffi.dll";
        return false;
    }
    return true;
}

bool SpiceBackend::createEngine()
{
    if (!m_fn_new) {
        m_error = "wowkispice_ffi_new not resolved";
        return false;
    }
    m_engine = m_fn_new();
    if (!m_engine) {
        m_error = "wowkispice_ffi_new returned null";
        return false;
    }
    return true;
}

void SpiceBackend::destroyEngine()
{
    if (m_engine && m_fn_destroy) {
        m_fn_destroy(m_engine);
        m_engine = nullptr;
    }
}

bool SpiceBackend::init()
{
    if (!m_engine || !m_fn_init) {
        m_error = "Engine not created";
        return false;
    }
    int rc = m_fn_init(m_engine);
    if (rc != 0) {
        m_error = QString("ngSpice_Init returned %1").arg(rc);
        return false;
    }
    return true;
}

bool SpiceBackend::cmd(const QString &command)
{
    if (!m_engine || !m_fn_cmd) {
        m_error = "Engine not created";
        return false;
    }
    QByteArray cmd = command.toLocal8Bit();
    int rc = m_fn_cmd(m_engine, cmd.constData());
    if (rc != 0) {
        m_error = QString("ngSpice_Command returned %1").arg(rc);
        return false;
    }
    return true;
}

bool SpiceBackend::loadCircuit(const QStringList &lines)
{
    if (!m_engine || !m_fn_load_circuit) {
        m_error = "Engine not created";
        return false;
    }

    // Convert QStringList to array of C strings
    QVector<QByteArray> cStrings;
    cStrings.reserve(lines.size());
    for (const QString &line : lines) {
        cStrings.append(line.toLocal8Bit());
    }

    // Build array of const char* pointers
    QVector<const char*> ptrs;
    ptrs.reserve(cStrings.size());
    for (const QByteArray &ba : cStrings) {
        ptrs.append(ba.constData());
    }

    int rc = m_fn_load_circuit(m_engine, ptrs.constData(), ptrs.size());
    if (rc != 0) {
        m_error = QString("ngSpice_Circ returned %1").arg(rc);
        return false;
    }
    return true;
}

QString SpiceBackend::curPlot() const
{
    if (!m_engine || !m_fn_cur_plot) {
        return QString();
    }
    const char *ptr = m_fn_cur_plot(m_engine);
    if (!ptr) {
        return QString();
    }
    return QString::fromLocal8Bit(ptr);
}

bool SpiceBackend::reset()
{
    if (!m_engine || !m_fn_reset) {
        m_error = "Engine not created";
        return false;
    }
    int rc = m_fn_reset(m_engine);
    if (rc != 0) {
        m_error = QString("ngSpice_Reset returned %1").arg(rc);
        return false;
    }
    return true;
}

bool SpiceBackend::getVectorArray(const QString &vecName, QVector<double> &out) const
{
    if (!m_engine || !m_fn_get_vector_array) {
        m_error = "Engine not created";
        return false;
    }

    QByteArray name = vecName.toLocal8Bit();
    int len = 0;
    // First call to get the length
    int rc = m_fn_get_vector_array(m_engine, name.constData(), nullptr, &len);
    if (rc != 0 || len <= 0) {
        m_error = QString("Vector '%1' not found").arg(vecName);
        return false;
    }

    // Allocate buffer and get data
    QVector<double> buffer(len);
    rc = m_fn_get_vector_array(m_engine, name.constData(), buffer.data(), &len);
    if (rc != 0) {
        m_error = QString("Failed to read vector '%1'").arg(vecName);
        return false;
    }

    out = buffer;
    return true;
}

double SpiceBackend::getLastSample(const QString &vecName) const
{
    if (!m_engine || !m_fn_get_last_sample) {
        return 0.0;
    }
    QByteArray name = vecName.toLocal8Bit();
    return m_fn_get_last_sample(m_engine, name.constData());
}
