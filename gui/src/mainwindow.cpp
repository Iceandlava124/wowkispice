#include "mainwindow.h"
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QFileDialog>
#include <QtWidgets/QInputDialog>
#include <QtWidgets/QTableWidget>
#include <QtWidgets/QHeaderView>
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
    setupPropertiesDock();

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

    auto *toolsMenu = menuBar()->addMenu("&Tools");
    toolsMenu->addAction("&Component Properties", this, &MainWindow::showComponentProperties);
    toolsMenu->addAction("&Model Library", m_schematicEditor, &SchematicEditor::modelLibraryManagement);

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
    auto *propsAction = toolBar->addAction("Properties");
    connect(propsAction, &QAction::triggered, this, &MainWindow::showComponentProperties);
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

void MainWindow::setupPropertiesDock()
{
    m_propertiesTable = new QTableWidget(0, 3, this);
    m_propertiesTable->setHorizontalHeaderLabels({"Parameter", "Value", "Description"});
    m_propertiesTable->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    m_propertiesTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_propertiesTable->verticalHeader()->hide();

    m_componentIdLabel = new QLabel("No component selected", this);
    m_componentIdLabel->setStyleSheet("QLabel { font-weight: bold; }");

    auto *layout = new QVBoxLayout();
    layout->addWidget(m_componentIdLabel);
    layout->addWidget(m_propertiesTable);

    auto *btnLayout = new QHBoxLayout();
    auto *saveBtn = new QPushButton("Save Changes", this);
    connect(saveBtn, &QPushButton::clicked, this, &MainWindow::saveComponentProperties);
    btnLayout->addWidget(saveBtn);
    layout->addLayout(btnLayout);

    QWidget *container = new QWidget(this);
    container->setLayout(layout);
    m_propertiesDock->setWidget(container);
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

    // Generate netlist from the drawn schematic
    QStringList deck = m_schematicEditor->generateNetlist();
    m_schematicEditor->setNetlist(deck);

    if (deck.isEmpty()) {
        QMessageBox::warning(this, "Empty Schematic",
            "No components in schematic. Add components first.");
        return;
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
        statusBar()->showMessage("Simulation ran but no time/v(out) vectors found");
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

// ---- Component properties ----

void MainWindow::showComponentProperties()
{
    // For now, show a dialog to edit the first component or prompt for component ID
    if (m_schematicEditor->netlist().isEmpty() && m_propertiesTable->rowCount() == 0) {
        // Show available components - for now just edit a default component
        bool ok;
        QString compId = QInputDialog::getText(this, "Component Properties",
            "Enter component ID to edit:", QLineEdit::Normal, "R1", &ok);
        if (!ok || compId.isEmpty())
            return;
        editComponentProperties(compId);
    } else {
        editComponentProperties(m_currentComponentId);
    }
}

void MainWindow::editComponentProperties(const QString &compId)
{
    m_currentComponentId = compId;
    m_componentIdLabel->setText("Component: " + compId);

    // Get component params from schematic editor
    m_propertiesTable->setRowCount(0);

    QStringList keys = {"value", "model"};
    for (const QString &key : keys) {
        QString currentVal = m_schematicEditor->componentParam(compId, key);
        if (currentVal.isEmpty()) {
            currentVal = m_schematicEditor->componentParam(compId, "value"); // fallback
        }

        int row = m_propertiesTable->rowCount();
        m_propertiesTable->insertRow(row);

        auto *nameItem = new QTableWidgetItem(key);
        nameItem->setFlags(nameItem->flags() & ~Qt::ItemIsEditable);
        m_propertiesTable->setItem(row, 0, nameItem);

        auto *valItem = new QTableWidgetItem(currentVal);
        m_propertiesTable->setItem(row, 1, valItem);

        QString desc;
        if (key == "value") desc = "Component value (e.g. 10k, 100n, PULSE(...))";
        else if (key == "model") desc = "SPICE model name";
        m_propertiesTable->setItem(row, 2, new QTableWidgetItem(desc));
    }

    m_propertiesDock->setWindowTitle("Properties — " + compId);
    m_propertiesDock->show();
}

void MainWindow::saveComponentProperties()
{
    if (m_currentComponentId.isEmpty())
        return;

    for (int row = 0; row < m_propertiesTable->rowCount(); ++row) {
        QTableWidgetItem *keyItem = m_propertiesTable->item(row, 0);
        QTableWidgetItem *valItem = m_propertiesTable->item(row, 1);
        if (keyItem && valItem) {
            m_schematicEditor->setComponentParam(m_currentComponentId,
                keyItem->text(), valItem->text());
        }
    }

    statusBar()->showMessage(QString("Properties saved for %1").arg(m_currentComponentId));
}
