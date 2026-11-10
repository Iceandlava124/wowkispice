#include "mainwindow.h"
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QFileDialog>
#include <QtCore/QDebug>
#include <QtCore/QTextStream>
#include <QtGui/QColor>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    setWindowTitle("WOWKISPICE Studio — LTspice + Wokwi");
    resize(1400, 900);

    setupMenuBar();
    setupToolBar();
    setupStatusBar();
    setupCentralWidget();
    setupDocks();

    // Initialize the ngspice backend
    if (m_spiceBackend.isAvailable()) {
        if (m_spiceBackend.createEngine() && m_spiceBackend.init()) {
            m_simulationReady = true;
            statusBar()->showMessage("Ready — ngspice backend connected");
        } else {
            statusBar()->showMessage(QString("Backend error: %1").arg(m_spiceBackend.errorString()));
        }
    } else {
        statusBar()->showMessage(QString("Backend unavailable: %1").arg(m_spiceBackend.errorString()));
    }
}

void MainWindow::setupMenuBar()
{
    auto *fileMenu = menuBar()->addMenu("&File");
    fileMenu->addAction("&Open Schematic...", this, &MainWindow::openSchematic, QKeySequence::Open);
    fileMenu->addAction("&Save", this, &MainWindow::saveSchematic, QKeySequence::Save);
    fileMenu->addSeparator();
    fileMenu->addAction("E&xit", this, &QWidget::close, QKeySequence::Quit);

    auto *simMenu = menuBar()->addMenu("&Simulation");
    simMenu->addAction("&Run Transient", this, &MainWindow::runTransient, QKeySequence("F5"));
    simMenu->addAction("&Stop", this, &MainWindow::stopSimulation, QKeySequence("Shift+F5"));
    simMenu->addSeparator();
    simMenu->addAction("&AC Analysis", this, &MainWindow::runAcAnalysis);
    simMenu->addAction("&DC Sweep", this, &MainWindow::runDcSweep);
    simMenu->addAction("&Noise", this, &MainWindow::runNoiseAnalysis);
    simMenu->addAction("&Fourier", this, &MainWindow::runFourierAnalysis);

    auto *viewMenu = menuBar()->addMenu("&View");
    viewMenu->addAction("&Schematic Editor", m_centralTabs, [this](){
        m_centralTabs->setCurrentWidget(m_schematicEditor);
    });
    viewMenu->addAction("&Waveform Viewer", m_centralTabs, [this](){
        m_centralTabs->setCurrentWidget(m_waveformViewer);
    });
    viewMenu->addAction("&Co-Sim Dashboard", m_centralTabs, [this](){
        m_centralTabs->setCurrentWidget(m_cosimDashboard);
    });
    viewMenu->addAction("&Code Workspace", m_centralTabs, [this](){
        m_centralTabs->setCurrentWidget(m_codeWorkspace);
    });

    auto *helpMenu = menuBar()->addMenu("&Help");
    helpMenu->addAction("&About", this, [](){
        QMessageBox::about(nullptr, "About WOWKISPICE",
            "WOWKISPICE Studio v0.1.0\n"
            "Closed-loop mixed-signal co-simulation GUI\n"
            "LTspice + Wokwi inspired\n"
            "4 views: Schematic Editor, Waveform Viewer, Co-Sim Dashboard, Code/Text Workspace\n"
            "Industrial Hardening: calibration, oversample, FSM verification, 16 industry tests");
    });
}

void MainWindow::setupToolBar()
{
    auto *toolBar = addToolBar("Main");
    toolBar->setObjectName("MainToolbar");
    auto *runAction = toolBar->addAction("Run");
    connect(runAction, &QAction::triggered, this, &MainWindow::runTransient);
    auto *stopAction = toolBar->addAction("Stop");
    connect(stopAction, &QAction::triggered, this, &MainWindow::stopSimulation);
    toolBar->addSeparator();
    toolBar->addAction("Zoom In");
    toolBar->addAction("Zoom Out");
    toolBar->addAction("Fit to Window");
}

void MainWindow::setupStatusBar()
{
    statusBar()->showMessage("Ready");
    statusBar()->addPermanentWidget(new QLabel("WOWKISPICE v0.1"));
}

void MainWindow::setupCentralWidget()
{
    m_centralTabs = new QTabWidget(this);
    m_centralTabs->setTabsClosable(false);
    m_centralTabs->setMovable(true);

    m_schematicEditor = new SchematicEditor(this);
    m_waveformViewer = new WaveformViewer(this);
    m_cosimDashboard = new CosimDashboard(this);
    m_codeWorkspace = new CodeWorkspace(this);

    m_centralTabs->addTab(m_schematicEditor, "Schematic Editor");
    m_centralTabs->addTab(m_waveformViewer, "Waveform Viewer");
    m_centralTabs->addTab(m_cosimDashboard, "Co-Sim Dashboard");
    m_centralTabs->addTab(m_codeWorkspace, "Code/Text Workspace");

    setCentralWidget(m_centralTabs);
}

void MainWindow::setupDocks()
{
    m_propertiesDock = new QDockWidget("Properties", this);
    m_propertiesDock->setWidget(new QLabel("Select a component to edit properties"));
    addDockWidget(Qt::RightDockWidgetArea, m_propertiesDock);

    m_consoleDock = new QDockWidget("Console", this);
    m_consoleDock->setWidget(new QLabel("Simulation console output will appear here"));
    addDockWidget(Qt::BottomDockWidgetArea, m_consoleDock);
}

// ---- Simulation actions ----

void MainWindow::openSchematic()
{
    QString fileName = QFileDialog::getOpenFileName(this, "Open Schematic",
        QString(), "Schematic files (*.sch *.cir *.net);;All files (*)");
    if (fileName.isEmpty())
        return;

    QFile file(fileName);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        QMessageBox::warning(this, "Open Error", "Cannot open file: " + fileName);
        return;
    }

    QTextStream in(&file);
    QStringList lines;
    while (!in.atEnd()) {
        lines << in.readLine();
    }
    file.close();

    if (m_simulationReady) {
        m_spiceBackend.reset();
        if (m_spiceBackend.loadCircuit(lines)) {
            statusBar()->showMessage(QString("Circuit loaded: %1").arg(fileName));
            m_schematicEditor->setNetlist(lines);
        } else {
            QMessageBox::warning(this, "Load Error",
                QString("Failed to load circuit: %1").arg(m_spiceBackend.errorString()));
        }
    } else {
        QMessageBox::warning(this, "Backend Not Ready",
            "ngspice backend is not available. Check that wowkispice_ffi.dll is present.");
    }
}

void MainWindow::saveSchematic()
{
    QString fileName = QFileDialog::getSaveFileName(this, "Save Schematic",
        QString(), "Schematic files (*.sch *.cir *.net);;All files (*)");
    if (fileName.isEmpty())
        return;

    QFile file(fileName);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        QMessageBox::warning(this, "Save Error", "Cannot save file: " + fileName);
        return;
    }

    QTextStream out(&file);
    const QStringList &lines = m_schematicEditor->netlist();
    for (const QString &line : lines) {
        out << line << "\n";
    }
    file.close();

    statusBar()->showMessage(QString("Saved: %1").arg(fileName));
}

void MainWindow::runTransient()
{
    if (!m_simulationReady) {
        QMessageBox::warning(this, "Backend Not Ready",
            "ngspice backend is not available.");
        return;
    }

    // Default transient analysis for a buck converter
    QStringList deck = m_schematicEditor->netlist();
    if (deck.isEmpty()) {
        // Built-in buck converter test circuit
        deck << "* Buck converter test circuit"
             << "V1 vin 0 PULSE(0 5 0 1n 1n 10u 20u)"
             << "L1 vin out 10u"
             << "D1 out 0 D1N4148"
             << "Rload out 0 10"
             << "C1 out 0 100u"
             << ".model D1N4148 D(Is=1e-9 N=1.8)"
             << ".tran 1u 5m uic"
             << ".end";
    }

    m_spiceBackend.reset();
    if (!m_spiceBackend.loadCircuit(deck)) {
        QMessageBox::warning(this, "Simulation Error",
            QString("Failed to load circuit: %1").arg(m_spiceBackend.errorString()));
        return;
    }

    if (!m_spiceBackend.cmd("run")) {
        QMessageBox::warning(this, "Simulation Error",
            QString("Simulation failed: %1").arg(m_spiceBackend.errorString()));
        return;
    }

    // Read back results
    QVector<double> time, vout;
    if (m_spiceBackend.getVectorArray("time", time) &&
        m_spiceBackend.getVectorArray("v(out)", vout)) {
        m_waveformViewer->addTrace("time", time, vout, Qt::blue);
        m_centralTabs->setCurrentWidget(m_waveformViewer);
        statusBar()->showMessage(QString("Transient complete: %1 points").arg(time.size()));
    } else {
        statusBar()->showMessage("Simulation ran but no data vectors found");
    }
}

void MainWindow::stopSimulation()
{
    statusBar()->showMessage("Simulation stopped");
}

void MainWindow::runAcAnalysis()
{
    QMessageBox::information(this, "AC Analysis",
        "AC Analysis uses the Co-Sim Dashboard's Bode plot feature.\n"
        "Switch to the Co-Sim Dashboard tab and configure the frequency sweep.");
    m_centralTabs->setCurrentWidget(m_cosimDashboard);
}

void MainWindow::runDcSweep()
{
    QMessageBox::information(this, "DC Sweep",
        "DC Sweep uses the Co-Sim Dashboard's Parameter Sweep feature.\n"
        "Switch to the Co-Sim Dashboard tab and configure the sweep.");
    m_centralTabs->setCurrentWidget(m_cosimDashboard);
}

void MainWindow::runNoiseAnalysis()
{
    QMessageBox::information(this, "Noise Analysis",
        "Noise analysis is not yet implemented.");
}

void MainWindow::runFourierAnalysis()
{
    QMessageBox::information(this, "Fourier Analysis",
        "Fourier analysis is not yet implemented.");
}
