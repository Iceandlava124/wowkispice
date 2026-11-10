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
#include <QtCore/QPair>
#include <QtCore/QPointF>

class QGraphicsRectItem;
class QGraphicsSimpleTextItem;

/// Represents a placed component with its SPICE parameters.
struct ComponentData {
    QString id;              // e.g. "R1", "V1", "Q1"
    QString type;            // e.g. "resistor", "capacitor", "voltage_source"
    QString spicePrefix;     // R, C, L, V, I, Q, D, M, X
    QPointF position;
    QMap<QString, QString> params;   // key=value pairs (e.g. "value"="10k", "model"="D1N4148")
    QMap<QString, QString> pinNets;  // pin name -> net name (e.g. "p1"="vin", "p2"="out")
};

/// Represents a net (electrical node) connecting component pins.
struct NetData {
    QString name;            // e.g. "vin", "out", "gnd"
    QVector<QString> pins;   // list of "componentId.pinName" connected to this net
};

/// Represents a drawn wire between two pins.
struct WireData {
    QString fromPin;   // "componentId.pinName"
    QString toPin;     // "componentId.pinName"
    QPointF fromPos;
    QPointF toPos;
};

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

    // Component parameter editing
    void setComponentParam(const QString &id, const QString &key, const QString &value);
    QString componentParam(const QString &id, const QString &key) const;

    // Netlist generation from the drawn schematic
    QStringList generateNetlist() const;

    // Netlist import/export for simulation
    QStringList netlist() const;
    void setNetlist(const QStringList &lines);

    // Component types available for placement
    QStringList availableComponentTypes() const;

    // Public placement methods (used by MainWindow)
    void startPlacingComponent(const QString &type);
    void cancelWire();
    QString componentIdAtScenePos(const QPointF &pos) const;

signals:
    void componentAdded(const QString &id, const QString &type, qreal x, qreal y);
    void wireAdded(const QString &fromPin, const QString &toPin);
    void netlistGenerated(const QStringList &lines);
    void componentDoubleClicked(const QString &id);
    void analysisComplete(const QString &results);

protected:
    // Mouse interaction for placing components and wires
    void mousePressEvent(QMouseEvent *event) override;
    void mouseDoubleClickEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;

private:
    QGraphicsScene *m_scene;
    QMap<QString, ComponentData> m_components;   // id -> component data
    QMap<QString, QPair<QPointF, QPointF>> m_wireEndpoints;
    QMap<QString, QString> m_componentModels;    // stored model names per component
    QStringList m_netlistLines;                  // stored SPICE netlist lines
    QVector<WireData> m_wires;                   // drawn wires

    // Mouse interaction state
    enum InteractionMode { SelectMode, PlaceComponentMode, PlaceWireMode };
    InteractionMode m_mode = SelectMode;
    QString m_placeType;                         // type to place when in PlaceComponentMode
    QString m_wireFromComponent;                 // component id for wire start
    QString m_wireFromPin;                       // pin name for wire start
    QPointF m_wireStartPos;                      // scene position of wire start
    QGraphicsLineItem *m_tempWire = nullptr;     // temporary wire being drawn

    QMap<QString, NetData> m_nets;               // net name -> net data
    QString m_currentComponentId;                // currently selected component id

    void importWAVStimulus(const QString &filePath);
    void showModelManagementDialog();
    QString resolveModelForType(const QString &type);
    QString spicePrefixForType(const QString &type) const;
    QString defaultValueForType(const QString &type) const;
    void buildNets();
    QString componentSpiceLine(const ComponentData &comp) const;
    QGraphicsItem *itemAtScenePos(const QPointF &pos) const;
    QPointF pinPosition(const QString &compId, const QString &pinName) const;
    void startPlacingWire(const QString &compId, const QString &pinName);
    void finishWire(const QPointF &endPos);
};

#endif // SCHEMATIC_EDITOR_H
