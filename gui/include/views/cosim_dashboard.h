#ifndef COSIM_DASHBOARD_H
#define COSIM_DASHBOARD_H

#include <QtWidgets/QWidget>
#include <QtWidgets/QTableWidget>
#include <QtWidgets/QPushButton>
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtWidgets/QDoubleSpinBox>
#include <QtWidgets/QSpinBox>
#include <QtWidgets/QComboBox>
#include <QtWidgets/QFrame>
#include <QtCore/QMap>
#include <QtCore/QString>
#include <QtCore/QVector>
#include <QtCharts/QChartView>

class CosimDashboard : public QWidget {
    Q_OBJECT
public:
    explicit CosimDashboard(QWidget *parent = nullptr);
    ~CosimDashboard() override = default;

    void addLaw(const QString &pin, double targetV, double hystV,
                int adcBits, double vref, double divider);
    void updateLawState(const QString &pin, bool gpioState,
                        int adcCounts, double senseV);
    void clearLaws();

    // Phase 5: Parameter sweep automation
    void startParameterSweep(int sweepType, int start, int stop, int steps,
                              double delayMs = 100.0);
    void stopParameterSweep();

    // Bode/frequency response analysis
    void requestBodeAnalysis(int componentId);

signals:
    void sweepProgress(int step, const QMap<QString, QMap<QString, double>> &results);
    void sweepComplete(const QMap<QString, QMap<QString, double>> &results);
    void bodeAnalysisReady(const QString &frequencyData, const QString &magnitudeData, const QString &phaseData);

public:
    void runSimulation();
    void stopSimulation();

private:
    QTableWidget *m_lawTable = nullptr;
    QPushButton *m_runBtn = nullptr;
    QPushButton *m_stopBtn = nullptr;
    QDoubleSpinBox *m_tstepSpin = nullptr;
    QDoubleSpinBox *m_durationSpin = nullptr;
    QDoubleSpinBox *m_vinSpin = nullptr;

    // Phase 5: parameter sweep UI
    QPushButton *m_sweepBtn = nullptr;
    QSpinBox *m_sweepStart = nullptr;
    QSpinBox *m_sweepStop = nullptr;
    QSpinBox *m_sweepSteps = nullptr;
    QDoubleSpinBox *m_sweepDelay = nullptr;
    QComboBox *m_sweepParam = nullptr;  // which parameter to sweep

    // Results display
    QTableWidget *m_sweepResults = nullptr;

    QMap<QString, int> m_lawRowMap;
    QMap<QString, bool> m_gpioState;
    QMap<QString, int> m_adcCounts;
    QMap<QString, double> m_senseV;

    // Bode analysis
    QtCharts::QChartView *m_bodeChartView = nullptr;
    QByteArray m_bodeFrequencyData;
    QByteArray m_bodeMagnitudeData;
    QByteArray m_bodePhaseData;

    void refreshTable();
    void updateSweepResults(const QMap<QString, QMap<QString, double>> &results);
};

#endif // COSIM_DASHBOARD_H