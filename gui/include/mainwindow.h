#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QtWidgets/QMainWindow>
#include <QtWidgets/QTabWidget>
#include <QtWidgets/QSplitter>
#include <QtWidgets/QMenuBar>
#include <QtWidgets/QStatusBar>
#include <QtWidgets/QToolBar>
#include <QtWidgets/QAction>
#include <QtWidgets/QDockWidget>
#include <QtWidgets/QTableWidget>
#include <QtWidgets/QLabel>

#include "views/schematic_editor.h"
#include "views/waveform_viewer.h"
#include "views/cosim_dashboard.h"
#include "views/code_workspace.h"
#include "spice_backend.h"

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QWidget *parent = nullptr);
    ~MainWindow() override = default;

private:
    void setupMenuBar();
    void setupToolBar();
    void setupStatusBar();
    void setupCentralWidget();
    void setupDocks();
    void setupPropertiesDock();

    // Simulation backend
    SpiceBackend m_spiceBackend;
    bool m_simulationReady = false;

    // Simulation actions
    void openSchematic();
    void saveSchematic();
    void runTransient();
    void stopSimulation();
    void runAcAnalysis();
    void runDcSweep();
    void runNoiseAnalysis();
    void runFourierAnalysis();

    // Component properties
    void showComponentProperties();
    void editComponentProperties(const QString &compId);
    void saveComponentProperties();

    QTabWidget *m_centralTabs = nullptr;

    // View widgets
    SchematicEditor *m_schematicEditor = nullptr;
    WaveformViewer *m_waveformViewer = nullptr;
    CosimDashboard *m_cosimDashboard = nullptr;
    CodeWorkspace *m_codeWorkspace = nullptr;

    // Dock widgets
    QDockWidget *m_propertiesDock = nullptr;
    QDockWidget *m_consoleDock = nullptr;

    // Properties dock widgets
    QTableWidget *m_propertiesTable = nullptr;
    QLabel *m_componentIdLabel = nullptr;
    QString m_currentComponentId;
};

#endif // MAINWINDOW_H
