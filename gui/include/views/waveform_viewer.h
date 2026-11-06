#ifndef WAVEFORM_VIEWER_H
#define WAVEFORM_VIEWER_H

#include <QtWidgets/QWidget>
#include <QtWidgets/QGraphicsView>
#include <QtWidgets/QGraphicsScene>
#include <QtWidgets/QGraphicsLineItem>
#include <QtCore/QVector>
#include <QtCore/QMap>
#include <QtCore/QString>
#include <QtGui/QColor>

class WaveformViewer : public QGraphicsView {
    Q_OBJECT
public:
    explicit WaveformViewer(QWidget *parent = nullptr);
    ~WaveformViewer() override = default;

    void addTrace(const QString &name, const QVector<double> &time, const QVector<double> &values, const QColor &color);
    void clearTraces();
    void setTimeRange(double t0, double t1);
    void setVoltageRange(double v0, double v1);

    void zoomIn();
    void zoomOut();
    void fitToWindow();

private:
    QGraphicsScene *m_scene = nullptr;
    QMap<QString, QVector<QGraphicsLineItem *>> m_traces;
    QMap<QString, QColor> m_traceColors;
    double m_t0 = 0.0, m_t1 = 5.0;
    double m_v0 = 0.0, m_v1 = 5.0;

    void drawGrid();
    void drawAxes();
    void redrawTraces();
};

#endif // WAVEFORM_VIEWER_H
