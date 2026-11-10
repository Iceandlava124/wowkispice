#ifndef SCHEMATIC_EDITOR_H
#define SCHEMATIC_EDITOR_H

#include <QtWidgets/QGraphicsView>
#include <QtWidgets/QGraphicsScene>
#include <QtWidgets/QGraphicsItem>
#include <QtWidgets/QGraphicsLineItem>
#include <QtWidgets/QGraphicsEllipseItem>
#include <QtWidgets/QGraphicsTextItem>
#include <QtCore/QMap>
#include <QtCore/QString>
#include <QtCore/QVector>

class QGraphicsRectItem;
class QGraphicsSimpleTextItem;

class SchematicEditor : public QGraphicsView
{
    Q_OBJECT

public:
    explicit SchematicEditor(QWidget *parent = nullptr);
    ~SchematicEditor() override = default;

    // Component management
    void addComponent(const QString &id, const QString &type, qreal x, qreal y);
    void addWire(const QString &fromPin, const QString &toPin);
    void importWAV();              // LTspice: WAV file as voltage stimulus
    void runBodeAnalysis();        // Frequency response / Bode plot
    void modelLibraryManagement(); // SPICE model/lib management

    // Netlist import/export for simulation
    QStringList netlist() const;
    void setNetlist(const QStringList &lines);

signals:
    void componentAdded(const QString &id, const QString &type, qreal x, qreal y);
    void wireAdded(const QString &fromPin, const QString &toPin);
    void analysisComplete(const QString &results);

private slots:
    void onAddComponent(const QString &type, qreal x, qreal y);

private:
    QGraphicsScene *m_scene;
    QMap<QString, QGraphicsRectItem *> m_components;
    QMap<QString, QPair<QPointF, QPointF>> m_wireEndpoints;
    QMap<QString, QString> m_componentModels;  // stored model names per component
    QStringList m_netlistLines;                // stored SPICE netlist lines

    void importWAVStimulus(const QString &filePath);
    void showModelManagementDialog();
    QString resolveModelForType(const QString &type);
};

#endif // SCHEMATIC_EDITOR_H