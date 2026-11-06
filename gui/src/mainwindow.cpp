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
    simMenu->addAction("&Run Transient", this, [](){}, QKeySequence("F5"));
    simMenu->addAction("&Stop", this, [](){}, QKeySequence("Shift+F5"));
    simMenu->addSeparator();
    simMenu->addAction("&AC Analysis", this, [](){});
    simMenu->addAction("&DC Sweep", this, [](){});
    simMenu->addAction("&Noise", this, [](){});
    simMenu->addAction("&Fourier", this, [](){});

    auto *viewMenu = menuBar()->addMenu("&View");
    viewMenu->addAction("&Schematic Editor", this, [](){});
    viewMenu->addAction("&Waveform Viewer", this, [](){});
    viewMenu->addAction("&Co-Sim Dashboard", this, [](){});
    viewMenu->addAction("&Code Workspace", this, [](){});

    auto *helpMenu = menuBar()->addMenu("&Help");
    helpMenu->addAction("&About", this, [](){
        QMessageBox::about(nullptr, "About WOWKISPICE",
            "WOWKISPICE Studio\n"
            "Closed-loop mixed-signal co-simulation GUI\n"
            "LTspice + Wokwi inspired\n"
            "4 views: Schematic Editor, Waveform Viewer, Co-Sim Dashboard, Code/Text Workspace");
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
