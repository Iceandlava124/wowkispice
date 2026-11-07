#include "../include/views/cosim_dashboard.h"
#include <QtWidgets/QHeaderView>
#include <QtWidgets/QMessageBox>
#include <QtCore/QTimer>
#include <QtCore/QDebug>
#include <QtCore/QStringLiteral>
#include <QtCharts/QChartView>
#include <QtCharts/QLineSeries>
#include <QtCharts/QValueAxis>

using namespace QtCharts;

CosimDashboard::CosimDashboard(QWidget *parent)
    : QWidget(parent)
{
    auto *layout = new QVBoxLayout(this);

    // Control panel
    auto *ctrlLayout = new QHBoxLayout();
    m_runBtn = new QPushButton("Run Co-Sim");
    m_stopBtn = new QPushButton("Stop");
    m_stopBtn->setEnabled(false);

    m_tstepSpin = new QDoubleSpinBox();
    m_tstepSpin->setRange(0.001, 100.0);
    m_tstepSpin->setValue(0.5);
    m_tstepSpin->setDecimals(3);
    m_tstepSpin->setSuffix(" A�s");

    m_durationSpin = new QDoubleSpinBox();
    m_durationSpin->setRange(1.0, 1000.0);
    m_durationSpin->setValue(5.0);
    m_durationSpin->setDecimals(1);
    m_durationSpin->setSuffix(" ms");

    m_vinSpin = new QDoubleSpinBox();
    m_vinSpin->setRange(0.0, 100.0);
    m_vinSpin->setValue(12.0);
    m_vinSpin->setDecimals(1);
    m_vinSpin->setSuffix(" V");

    ctrlLayout->addWidget(new QLabel("Tstep:"));
    ctrlLayout->addWidget(m_tstepSpin);
    ctrlLayout->addWidget(new QLabel("Duration:"));
    ctrlLayout->addWidget(m_durationSpin);
    ctrlLayout->addWidget(new QLabel("VIN:"));
    ctrlLayout->addWidget(m_vinSpin);

    // Phase 5: Parameter sweep controls
    m_sweepBtn = new QPushButton("Param Sweep");
    m_sweepStart = new QSpinBox();
    m_sweepStart->setRange(0, 4095);
    m_sweepStart->setValue(1500);
    m_sweepStop = new QSpinBox();
    m_sweepStop->setRange(0, 4095);
    m_sweepStop->setValue(2500);
    m_sweepSteps = new QSpinBox();
    m_sweepSteps->setRange(1, 100);
    m_sweepSteps->setValue(10);
    m_sweepDelay = new QDoubleSpinBox();
    m_sweepDelay->setRange(0.1, 10.0);
    m_sweepDelay->setValue(100.0);
    m_sweepDelay->setSuffix(" ms");
    m_sweepParam = new QComboBox();
    m_sweepParam->addItem("ADC Counts", 0);
    m_sweepParam->addItem("Voltage (mV)", 1);
    m_sweepParam->addItem("Gate State", 2);

    ctrlLayout->addWidget(new QLabel("Sweep:"));
    ctrlLayout->addWidget(m_sweepStart);
    ctrlLayout->addWidget(m_sweepStop);
    ctrlLayout->addWidget(new QLabel("Steps:"));
    ctrlLayout->addWidget(m_sweepSteps);
    ctrlLayout->addWidget(new QLabel("Delay(ms):"));
    ctrlLayout->addWidget(m_sweepDelay);
    ctrlLayout->addWidget(new QLabel("Param:"));
    ctrlLayout->addWidget(m_sweepParam);
    ctrlLayout->addStretch();
    ctrlLayout->addWidget(m_runBtn);
    ctrlLayout->addWidget(m_stopBtn);
    ctrlLayout->addWidget(m_sweepBtn);

    layout->addLayout(ctrlLayout);

    // Law table
    m_lawTable = new QTableWidget(0, 6, this);
    QStringList headers = {"MCU Pin", "Target V", "Hyst V", "ADC Bits", "Vref", "Divider"};
    m_lawTable->setHorizontalHeaderLabels(headers);
    m_lawTable->horizontalHeader()->setStretchLastSection(true);
    m_lawTable->setAlternatingRowColors(true);
    m_lawTable->setSelectionBehavior(QAbstractItemView::SelectRows);

    layout->addWidget(m_lawTable);

    // Phase 5: Sweep results table
    m_sweepResults = new QTableWidget(0, 4, this);
    m_sweepResults->setHorizontalHeaderLabels({"Parameter", "Gate State", "ADC Counts", "Status"});
    m_sweepResults->horizontalHeader()->setStretchLastSection(true);

    layout->addWidget(m_sweepResults);

    // Status
    auto *statusLayout = new QHBoxLayout();
    auto *statusLabel = new QLabel("Status: Idle");
    statusLabel->setStyleSheet("QLabel { font-weight: bold; }");
    statusLayout->addWidget(statusLabel);
    statusLayout->addStretch();
    layout->addLayout(statusLayout);

    // Phase 5: Bode plot chart view
    m_bodeChartView = new QChartView(this);
    m_bodeChartView->setRenderHint(QPainter::Antialiasing);
    // Set up default empty chart
    QChart *chart = new QChart();
    chart->setTitle("Bode Plot - Magnitude vs Frequency");
    chart->legend()->hide();
    QValueAxis *magnAxis = new QValueAxis();
    magnAxis->setLabelFormat("%.2f");
    magnAxis->setTitleText("Magnitude (dB)");
    QValueAxis *freqAxis = new QValueAxis();
    freqAxis->setLabelFormat("%.2f");
    freqAxis->setTitleText("Frequency (Hz)");
    chart->addAxis(magnAxis, Qt::AlignLeft);
    chart->addAxis(freqAxis, Qt::AlignBottom);
    QLineSeries *magnSeries = new QLineSeries();
    QLineSeries *phaseSeries = new QLineSeries();
    chart->addSeries(magnSeries);
    chart->addSeries(phaseSeries);
    magnSeries->attachAxis(magnAxis);
    phaseSeries->attachAxis(magnAxis);
    magnSeries->attachAxis(freqAxis);
    phaseSeries->attachAxis(freqAxis);
    m_bodeChartView->setChart(chart);

    layout->addWidget(m_bodeChartView);

    // Connections
    connect(m_runBtn, &QPushButton::clicked, this, &CosimDashboard::runSimulation);
    connect(m_stopBtn, &QPushButton::clicked, this, &CosimDashboard::stopSimulation);
    connect(m_sweepBtn, &QPushButton::clicked, this, [this] {
        startParameterSweep(m_sweepParam->currentIndex(), m_sweepStart->value(),
                            m_sweepStop->value(), m_sweepSteps->value(),
                            m_sweepDelay->value());
    });
}

void CosimDashboard::addLaw(const QString &pin, double targetV, double hystV,
                             int adcBits, double vref, double divider)
{
    if (m_lawRowMap.contains(pin)) return;

    int row = m_lawTable->rowCount();
    m_lawTable->insertRow(row);
    m_lawTable->setItem(row, 0, new QTableWidgetItem(pin));
    m_lawTable->setItem(row, 1, new QTableWidgetItem(QString::number(targetV, 'f', 3)));
    m_lawTable->setItem(row, 2, new QTableWidgetItem(QString::number(hystV, 'f', 3)));
    m_lawTable->setItem(row, 3, new QTableWidgetItem(QString::number(adcBits)));
    m_lawTable->setItem(row, 4, new QTableWidgetItem(QString::number(vref, 'f', 2)));
    m_lawTable->setItem(row, 5, new QTableWidgetItem(QString::number(divider, 'f', 2)));

    m_lawRowMap[pin] = row;
    m_gpioState[pin] = false;
    m_adcCounts[pin] = 0;
    m_senseV[pin] = 0.0;
}

void CosimDashboard::updateLawState(const QString &pin, bool gpioState,
                                     int adcCounts, double senseV)
{
    if (!m_lawRowMap.contains(pin)) return;

    int row = m_lawRowMap[pin];
    m_gpioState[pin] = gpioState;
    m_adcCounts[pin] = adcCounts;
    m_senseV[pin] = senseV;

    // Update row colors based on GPIO state
    QColor color = gpioState ? QColor("#c8e6c9") : QColor("#ffcdd2");
    for (int col = 0; col < 6; ++col) {
        auto *item = m_lawTable->item(row, col);
        if (item) item->setBackground(color);
    }

    // Add status info
    auto *statusItem = new QTableWidgetItem(
        QString("GPIO=%1 ADC=%2 V=%3V")
        .arg(gpioState ? "HIGH" : "LOW")
        .arg(adcCounts)
        .arg(senseV, 0, 'f', 2));
    m_lawTable->setItem(row, 6, statusItem);
}

void CosimDashboard::clearLaws()
{
    m_lawTable->setRowCount(0);
    m_lawRowMap.clear();
    m_gpioState.clear();
    m_adcCounts.clear();
    m_senseV.clear();
    // Clear sweep results
    m_sweepResults->setRowCount(0);
}

void CosimDashboard::runSimulation()
{
    m_runBtn->setEnabled(false);
    m_stopBtn->setEnabled(true);

    qDebug() << "Starting co-simulation with" << m_lawTable->rowCount() << "laws";
}

void CosimDashboard::stopSimulation()
{
    m_runBtn->setEnabled(true);
    m_stopBtn->setEnabled(false);
}

// Phase 5: Parameter sweep automation
void CosimDashboard::startParameterSweep(int sweepType, int start, int stop, int steps,
                                           double delayMs)
{
    qDebug() << "Starting parameter sweep type" << sweepType
             << "range" << start << "to" << stop << steps << "steps";
    Q_UNUSED(delayMs);

    m_sweepResults->setRowCount(0);

    // Determine what to sweep based on m_sweepParam selection
    QString paramName;
    int stepCount = steps;

    if (m_sweepParam->currentIndex() == 0) {  // ADC Counts
        paramName = "ADC Counts";
    } else if (m_sweepParam->currentIndex() == 1) {  // Voltage
        paramName = "Voltage (mV)";
        // Convert ADC to approximate voltage: V = ADC * Vref / 4095
        // We'll use the VIN from the control panel
    } else {  // Gate State - just toggle
        paramName = "Gate State";
    }

    // Add header row
    m_sweepResults->setColumnCount(4);
    m_sweepResults->setHorizontalHeaderLabels({"Parameter", "Gate State", "ADC Counts", "Status"});

    // Simulate the sweep (in real impl, this would call the DLL/F)
    for (int i = 0; i <= stepCount; ++i) {
        int currentVal;
        if (sweepType == 0) {  // Linear sweep
            currentVal = start + (int)((double)(stop - start) * i / steps);
        } else {  // Custom
            currentVal = start;
        }

        // Simulate tick for this value
        bool gateState = false;
        if (currentVal < 1995) gateState = true;
        else if (currentVal > 2030) gateState = false;
        // else hysteresis holds

        // Add row to results
        m_sweepResults->insertRow(i);
        m_sweepResults->setItem(i, 0, new QTableWidgetItem(paramName));
        m_sweepResults->setItem(i, 1, new QTableWidgetItem(gateState ? "HIGH" : "LOW"));
        m_sweepResults->setItem(i, 2, new QTableWidgetItem(QString::number(currentVal)));
        m_sweepResults->setItem(i, 3, new QTableWidgetItem("Complete"));
    }

    // Emit progress signal (simulated - in real impl would emit per step)
    QMap<QString, QMap<QString, double>> results;
    for (int i = 0; i <= stepCount; ++i) {
        QMap<QString, double> stepResults;
        int adc = start + (int)((double)(stop - start) * i / steps);
        stepResults["adc"] = adc;
        stepResults["gate"] = (adc < 1995) ? 1.0 : 0.0;
        results[QString::number(i)] = stepResults;
    }
    emit sweepProgress(0, results);
    emit sweepComplete(results);
}

void CosimDashboard::stopParameterSweep()
{
    qDebug() << "Parameter sweep stopped";
}