#include "mainwindow.h"
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QFileDialog>
#include <QtWidgets/QInputDialog>
#include <QtWidgets/QTableWidget>
#include <QtWidgets/QHeaderView>
#include <QtWidgets/QPushButton>
#include <QtWidgets/QToolButton>
#include <QtWidgets/QButtonGroup>
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

    // Connect schematic editor signals
    connect(m_schematicEditor, &SchematicEditor::componentDoubleClicked,
            this, &MainWindow::editComponentProperties);
    connect(m_schematicEditor, &SchematicEditor::netlistGenerated,
            this, [this](const QStringList &lines) {
                m_schematicEditor->setNetlist(lines);
            });
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

    // --- Component placement group ---
    toolBar->addSeparator();
    auto *compLabel = new QLabel("Components: ", this);
    toolBar->addWidget(compLabel);

    auto *btnResistor = new QToolButton(this);
    btnResistor->setText("R");
    btnResistor->setToolTip("Place Resistor");
    btnResistor->setCheckable(true);
    connect(btnResistor, &QToolButton::clicked, this, [this](){ placeComponent("resistor"); });

    auto *btnCapacitor = new QToolButton(this);
    btnCapacitor->setText("C");
    btnCapacitor->setToolTip("Place Capacitor");
    btnCapacitor->setCheckable(true);
    connect(btnCapacitor, &QToolButton::clicked, this, [this](){ placeComponent("capacitor"); });

    auto *btnInductor = new QToolButton(this);
    btnInductor->setText("L");
    btnInductor->setToolTip("Place Inductor");
    btnInductor->setCheckable(true);
    connect(btnInductor, &QToolButton::clicked, this, [this](){ placeComponent("inductor"); });

    auto *btnVoltage = new QToolButton(this);
    btnVoltage->setText("V");
    btnVoltage->setToolTip("Place Voltage Source");
    btnVoltage->setCheckable(true);
    connect(btnVoltage, &QToolButton::clicked, this, [this](){ placeComponent("voltage_source"); });

    auto *btnDiode = new QToolButton(this);
    btnDiode->setText("D");
    btnDiode->setToolTip("Place Diode");
    btnDiode->setCheckable(true);
    connect(btnDiode, &QToolButton::clicked, this, [this](){ placeComponent("diode"); });

    toolBar->addWidget(btnResistor);
    toolBar->addWidget(btnCapacitor);
    toolBar->addWidget(btnInductor);
    toolBar->addWidget(btnVoltage);
    toolBar->addWidget(btnDiode);

    // --- Wire mode ---
    toolBar->addSeparator();
    auto *btnWire = new QToolButton(this);
    btnWire->setText("Wire");
    btnWire->setToolTip("Place Wire (click pin to pin)");
    btnWire->setCheckable(true);
    connect(btnWire, &QToolButton::clicked, this, [this](bool checked){ 
        if (checked) setWireMode(); 
        else m_schematicEditor->cancelWire(); 
    });
    toolBar->addWidget(btnWire);

    // --- Simulation ---
    toolBar->addSeparator();
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
    if (!m_simulationReady) {
        QMessageBox::warning(this, "Backend Not Ready",
            "ngspice backend is not available.");
        return;
    }

    QStringList deck = m_schematicEditor->generateNetlist();
    if (deck.isEmpty()) {
        QMessageBox::warning(this, "Empty Schematic",
            "No components in schematic. Add components first.");
        return;
    }

    // Replace analysis card with AC sweep
    QStringList acDeck;
    bool replaced = false;
    for (const QString &line : deck) {
        if (line.startsWith(".tran") || line.startsWith(".ac") || line.startsWith(".dc")) {
            acDeck << ".ac dec 100 10 1Meg";
            replaced = true;
        } else {
            acDeck << line;
        }
    }
    if (!replaced) {
        acDeck << ".ac dec 100 10 1Meg";
    }
    acDeck << ".end";

    m_spiceBackend.reset();
    if (!m_spiceBackend.loadCircuit(acDeck)) {
        QMessageBox::warning(this, "AC Analysis Error",
            QString("Failed to load circuit: %1").arg(m_spiceBackend.errorString()));
        return;
    }

    if (!m_spiceBackend.cmd("run")) {
        QMessageBox::warning(this, "AC Analysis Error",
            QString("Simulation failed: %1").arg(m_spiceBackend.errorString()));
        return;
    }

    // Read back frequency and magnitude/phase
    QVector<double> freq, mag, phase;
    if (m_spiceBackend.getVectorArray("frequency", freq) &&
        m_spiceBackend.getVectorArray("v(out)", mag)) {
        // For AC, vectors are complex - magnitude is stored in v(out)
        m_waveformViewer->addTrace("frequency", freq, mag, Qt::blue);
        m_centralTabs->setCurrentWidget(m_waveformViewer);
        statusBar()->showMessage(QString("AC Analysis complete: %1 points").arg(freq.size()));
    } else {
        statusBar()->showMessage("AC Analysis ran but no frequency/v(out) vectors found");
    }
}

void MainWindow::runDcSweep()
{
    if (!m_simulationReady) {
        QMessageBox::warning(this, "Backend Not Ready",
            "ngspice backend is not available.");
        return;
    }

    QStringList deck = m_schematicEditor->generateNetlist();
    if (deck.isEmpty()) {
        QMessageBox::warning(this, "Empty Schematic",
            "No components in schematic. Add components first.");
        return;
    }

    // Replace analysis card with DC sweep
    QStringList dcDeck;
    bool replaced = false;
    for (const QString &line : deck) {
        if (line.startsWith(".tran") || line.startsWith(".ac") || line.startsWith(".dc")) {
            dcDeck << ".dc V1 0 5 0.1";
            replaced = true;
        } else {
            dcDeck << line;
        }
    }
    if (!replaced) {
        dcDeck << ".dc V1 0 5 0.1";
    }
    dcDeck << ".end";

    m_spiceBackend.reset();
    if (!m_spiceBackend.loadCircuit(dcDeck)) {
        QMessageBox::warning(this, "DC Sweep Error",
            QString("Failed to load circuit: %1").arg(m_spiceBackend.errorString()));
        return;
    }

    if (!m_spiceBackend.cmd("run")) {
        QMessageBox::warning(this, "DC Sweep Error",
            QString("Simulation failed: %1").arg(m_spiceBackend.errorString()));
        return;
    }

    QVector<double> sweep, vout;
    if (m_spiceBackend.getVectorArray("v1", sweep) &&
        m_spiceBackend.getVectorArray("v(out)", vout)) {
        m_waveformViewer->addTrace("v1", sweep, vout, Qt::blue);
        m_centralTabs->setCurrentWidget(m_waveformViewer);
        statusBar()->showMessage(QString("DC Sweep complete: %1 points").arg(sweep.size()));
    } else {
        statusBar()->showMessage("DC Sweep ran but no vectors found");
    }
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

// ---- Component placement ----

void MainWindow::placeComponent(const QString &type)
{
    m_schematicEditor->startPlacingComponent(type);
    statusBar()->showMessage(QString("Click to place %1...").arg(type));
}

void MainWindow::setWireMode()
{
    m_schematicEditor->cancelWire(); // cancel any existing wire
    statusBar()->showMessage("Wire mode: click pin to pin to connect");
}

// ---- Component properties ----

void MainWindow::showComponentProperties()
{
    if (m_schematicEditor->componentIdAtScenePos(QPointF()).isEmpty() && m_currentComponentId.isEmpty()) {
        // Prompt for component ID
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
