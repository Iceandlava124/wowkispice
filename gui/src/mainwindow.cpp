#include "mainwindow.h"
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtWidgets/QMessageBox>
#include <QtCore/QDebug>

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

    statusBar()->showMessage("Ready — no circuit loaded");
}

void MainWindow::setupMenuBar()
{
    auto *fileMenu = menuBar()->addMenu("&File");
    fileMenu->addAction("&Open Schematic...", this, [](){}, QKeySequence::Open);
    fileMenu->addAction("&Save", this, [](){}, QKeySequence::Save);
    fileMenu->addSeparator();
    fileMenu->addAction("E&xit", this, &QWidget::close, QKeySequence::Quit);

    auto *simMenu = menuBar()->addMenu("&Simulation");
    simMenu->addAction("&Run Transient", this, [](){
        QMessageBox::information(nullptr, "Run Transient",
            "Transient simulation not yet connected to backend.\n"
            "Use the Co-Sim Dashboard to run simulations once ngspice bridge is connected.");
    }, QKeySequence("F5"));
    simMenu->addAction("&Stop", this, [](){}, QKeySequence("Shift+F5"));
    simMenu->addSeparator();
    simMenu->addAction("&AC Analysis", this, [](){
        QMessageBox::information(nullptr, "AC Analysis",
            "AC Analysis not yet implemented.\n"
            "Use the Co-Sim Dashboard's Bode plot feature for frequency analysis.");
    });
    simMenu->addAction("&DC Sweep", this, [](){
        QMessageBox::information(nullptr, "DC Sweep",
            "DC Sweep not yet implemented.\n"
            "Use the Co-Sim Dashboard's Parameter Sweep feature.");
    });
    simMenu->addAction("&Noise", this, [](){
        QMessageBox::information(nullptr, "Noise Analysis",
            "Noise analysis not yet implemented.");
    });
    simMenu->addAction("&Fourier", this, [](){
        QMessageBox::information(nullptr, "Fourier Analysis",
            "Fourier analysis not yet implemented.");
    });

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
    toolBar->addAction("Open Schematic");
    toolBar->addAction("Run");
    toolBar->addAction("Stop");
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
