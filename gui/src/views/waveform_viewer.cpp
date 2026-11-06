#include "../include/views/waveform_viewer.h"
#include <QtWidgets/QGraphicsScene>
#include <QtWidgets/QGraphicsLineItem>
#include <QtWidgets/QGraphicsTextItem>
#include <QtCore/QDebug>

WaveformViewer::WaveformViewer(QWidget *parent)
    : QGraphicsView(parent)
{
    m_scene = new QGraphicsScene(this);
    m_scene->setSceneRect(0, 0, 1000, 400);
    setScene(m_scene);
    setRenderHint(QPainter::Antialiasing);

    m_t0 = 0.0; m_t1 = 5.0;
    m_v0 = 0.0; m_v1 = 5.0;

    drawGrid();
    drawAxes();
}

void WaveformViewer::addTrace(const QString &name, const QVector<double> &time,
                               const QVector<double> &values, const QColor &color)
{
    m_traceColors[name] = color;
    QVector<QGraphicsLineItem *> lines;
    int n = qMin(time.size(), values.size());
    if (n < 2) return;

    for (int i = 1; i < n; ++i) {
        double x1 = ((time[i-1] - m_t0) / (m_t1 - m_t0)) * 950 + 25;
        double y1 = 375 - ((values[i-1] - m_v0) / (m_v1 - m_v0)) * 350;
        double x2 = ((time[i] - m_t0) / (m_t1 - m_t0)) * 950 + 25;
        double y2 = 375 - ((values[i] - m_v0) / (m_v1 - m_v0)) * 350;

        auto *line = m_scene->addLine(x1, y1, x2, y2, QPen(color, 2));
        lines.append(line);
    }
    m_traces[name] = lines;

    // Add label
    auto *label = m_scene->addText(name);
    label->setPos(10, 10 + m_traces.size() * 20);
    label->setDefaultTextColor(color);
}

void WaveformViewer::clearTraces()
{
    for (auto &lines : m_traces) {
        for (auto *line : lines) {
            m_scene->removeItem(line);
            delete line;
        }
        lines.clear();
    }
    m_traces.clear();
    m_traceColors.clear();
    redrawTraces();
}

void WaveformViewer::setTimeRange(double t0, double t1)
{
    m_t0 = t0; m_t1 = t1;
    redrawTraces();
}

void WaveformViewer::setVoltageRange(double v0, double v1)
{
    m_v0 = v0; m_v1 = v1;
    redrawTraces();
}

void WaveformViewer::zoomIn()
{
    double mid = (m_t0 + m_t1) / 2;
    double span = (m_t1 - m_t0) * 0.5;
    m_t0 = mid - span / 2;
    m_t1 = mid + span / 2;
    redrawTraces();
}

void WaveformViewer::zoomOut()
{
    double mid = (m_t0 + m_t1) / 2;
    double span = (m_t1 - m_t0) * 2.0;
    m_t0 = mid - span / 2;
    m_t1 = mid + span / 2;
    redrawTraces();
}

void WaveformViewer::fitToWindow()
{
    redrawTraces();
}

void WaveformViewer::drawGrid()
{
    QPen gridPen(QColor("#e0e0e0"), 1);
    for (int x = 25; x <= 975; x += 50) {
        m_scene->addLine(x, 0, x, 400, gridPen);
    }
    for (int y = 25; y <= 375; y += 50) {
        m_scene->addLine(0, y, 1000, y, gridPen);
    }
}

void WaveformViewer::drawAxes()
{
    QPen axisPen(Qt::black, 2);
    m_scene->addLine(25, 375, 975, 375, axisPen);  // X axis
    m_scene->addLine(25, 0, 25, 375, axisPen);     // Y axis

    auto *tLabel = m_scene->addText("Time (ms)");
    tLabel->setPos(480, 385);

    auto *vLabel = m_scene->addText("Voltage (V)");
    vLabel->setPos(5, 180);
    vLabel->setRotation(-90);
}

void WaveformViewer::redrawTraces()
{
    // Clear existing trace lines but keep grid and axes
    for (auto &lines : m_traces) {
        for (auto *line : lines) {
            m_scene->removeItem(line);
            delete line;
        }
        lines.clear();
    }

    // We would need to re-add traces with new scaling
    // For now, just refresh
    m_scene->update();
}
