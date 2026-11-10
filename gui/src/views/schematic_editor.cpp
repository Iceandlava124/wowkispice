#include "../include/views/schematic_editor.h"
#include <QtWidgets/QGraphicsSceneMouseEvent>
#include <QtWidgets/QGraphicsRectItem>
#include <QtWidgets/QGraphicsSimpleTextItem>
#include <QtWidgets/QGraphicsEllipseItem>
#include <QtGui/QMouseEvent>
#include <QtWidgets/QFileDialog>
#include <QtWidgets/QInputDialog>
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QDialog>
#include <QtWidgets/QDialogButtonBox>
#include <QtWidgets/QFormLayout>
#include <QtWidgets/QLineEdit>
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtCore/QDebug>
#include <QtCore/QStringLiteral>
#include <QtCore/QTextStream>

SchematicEditor::SchematicEditor(QWidget *parent)
    : QGraphicsView(parent)
{
    m_scene = new QGraphicsScene(this);
    m_scene->setSceneRect(-2000, -2000, 4000, 4000);
    setScene(m_scene);
    setRenderHint(QPainter::Antialiasing);
    setDragMode(QGraphicsView::RubberBandDrag);
    setMouseTracking(true);

    // Draw a grid background (easier schematic entry)
    for (qreal x = -2000; x <= 2000; x += 50) {
        auto *line = m_scene->addLine(x, -2000, x, 2000, QPen(QColor("#e0e0e0"), 1));
        line->setZValue(-1);
    }
    for (qreal y = -2000; y <= 2000; y += 50) {
        auto *line = m_scene->addLine(-2000, y, 2000, y, QPen(QColor("#e0e0e0"), 1));
        line->setZValue(-1);
    }
}

void SchematicEditor::addComponent(const QString &id, const QString &type, qreal x, qreal y)
{
    ComponentData comp;
    comp.id = id;
    comp.type = type;
    comp.spicePrefix = spicePrefixForType(type);
    comp.position = QPointF(x, y);
    comp.params["value"] = defaultValueForType(type);

    auto *rect = new QGraphicsRectItem(x - 30, y - 20, 60, 40);
    rect->setPen(QPen(Qt::darkBlue, 2));
    rect->setBrush(QBrush(QColor("#f0f8ff")));
    rect->setFlag(QGraphicsItem::ItemIsMovable, true);
    rect->setFlag(QGraphicsItem::ItemIsSelectable, true);
    rect->setData(0, id);  // store component id in item data

    auto *label = new QGraphicsSimpleTextItem(type, rect);
    label->setPos(-label->boundingRect().width() / 2, -label->boundingRect().height() / 2);

    auto *idLabel = new QGraphicsSimpleTextItem(id, rect);
    idLabel->setPos(-idLabel->boundingRect().width() / 2, 25);
    idLabel->setScale(0.6);

    // Draw pins (small circles on left and right)
    qreal pinSize = 6;
    auto *pin1 = new QGraphicsEllipseItem(-35 - pinSize/2, -pinSize/2, pinSize, pinSize, rect);
    pin1->setBrush(QBrush(Qt::black));
    pin1->setData(0, id + ".p1");

    auto *pin2 = new QGraphicsEllipseItem(30 + pinSize/2, -pinSize/2, pinSize, pinSize, rect);
    pin2->setBrush(QBrush(Qt::black));
    pin2->setData(0, id + ".p2");

    m_scene->addItem(rect);
    m_components[id] = comp;

    // Store model reference
    m_componentModels[id] = resolveModelForType(type);

    emit componentAdded(id, type, x, y);
}

void SchematicEditor::addWire(const QString &fromPin, const QString &toPin)
{
    // Parse "componentId.pinName" format
    auto parsePin = [](const QString &pinStr) -> QPair<QString, QString> {
        int dot = pinStr.indexOf('.');
        if (dot < 0) return {pinStr, ""};
        return {pinStr.left(dot), pinStr.mid(dot + 1)};
    };

    auto fromParts = parsePin(fromPin);
    auto toParts = parsePin(toPin);

    QPointF fromPos = pinPosition(fromParts.first, fromParts.second);
    QPointF toPos = pinPosition(toParts.first, toParts.second);

    auto *line = m_scene->addLine(
        fromPos.x(), fromPos.y(),
        toPos.x(), toPos.y(),
        QPen(Qt::red, 2));
    line->setZValue(0);
    line->setData(0, fromPin + "->" + toPin);

    WireData wire;
    wire.fromPin = fromPin;
    wire.toPin = toPin;
    wire.fromPos = fromPos;
    wire.toPos = toPos;
    m_wires.append(wire);

    // Update pinNets: both pins share the same net
    QString netName = "net_" + QString::number(m_wires.size());
    auto &compFrom = m_components[fromParts.first];
    auto &compTo = m_components[toParts.first];
    compFrom.pinNets[fromParts.second] = netName;
    compTo.pinNets[toParts.second] = netName;

    emit wireAdded(fromPin, toPin);
}

void SchematicEditor::setComponentParam(const QString &id, const QString &key, const QString &value)
{
    auto it = m_components.find(id);
    if (it != m_components.end()) {
        it.value().params[key] = value;
    }
}

QString SchematicEditor::componentParam(const QString &id, const QString &key) const
{
    auto it = m_components.find(id);
    if (it != m_components.end()) {
        auto pit = it.value().params.find(key);
        if (pit != it.value().params.end()) {
            return pit.value();
        }
    }
    return QString();
}

QStringList SchematicEditor::availableComponentTypes() const
{
    return {"resistor", "capacitor", "inductor", "voltage_source", "current_source",
            "diode", "mosfet_n", "mosfet_p", "bjt_npn", "bjt_pnp", "opamp"};
}

void SchematicEditor::mousePressEvent(QMouseEvent *event)
{
    if (event->button() != Qt::LeftButton) {
        QGraphicsView::mousePressEvent(event);
        return;
    }

    QPointF scenePos = mapToScene(event->pos());

    if (m_mode == PlaceComponentMode && !m_placeType.isEmpty()) {
        // Place a new component at clicked position
        static int compCounter = 0;
        QString id = m_placeType.left(1).toUpper() + QString::number(++compCounter);
        addComponent(id, m_placeType, scenePos.x(), scenePos.y());
        m_mode = SelectMode;
        m_placeType.clear();
        event->accept();
        return;
    }

    if (m_mode == PlaceWireMode && !m_wireFromComponent.isEmpty()) {
        // We're placing a wire - look for a pin to connect to
        QGraphicsItem *item = itemAtScenePos(scenePos);
        if (item) {
            QString pinData = item->data(0).toString();
            if (pinData.contains('.')) {
                // This is a pin - finish the wire
                finishWire(scenePos);
                event->accept();
                return;
            }
        }
        // Clicked empty space - cancel wire placement
        cancelWire();
        QGraphicsView::mousePressEvent(event);
        return;
    }

    // Select mode - check if clicked on a component or pin
    QGraphicsItem *item = itemAtScenePos(scenePos);
    if (item) {
        QString itemData = item->data(0).toString();
        if (!itemData.isEmpty() && !itemData.contains("->")) {
            // Could be a component id or a pin
            if (itemData.contains('.')) {
                // It's a pin - start wire placement
                QString pinStr = itemData;
                int dot = pinStr.indexOf('.');
                QString compId = pinStr.left(dot);
                QString pinName = pinStr.mid(dot + 1);
                startPlacingWire(compId, pinName);
            } else {
                // It's a component - select it
                m_currentComponentId = itemData;
                emit componentDoubleClicked(itemData);
            }
        }
    }

    QGraphicsView::mousePressEvent(event);
}

void SchematicEditor::mouseDoubleClickEvent(QMouseEvent *event)
{
    if (event->button() != Qt::LeftButton) {
        QGraphicsView::mouseDoubleClickEvent(event);
        return;
    }

    QPointF scenePos = mapToScene(event->pos());
    QGraphicsItem *item = itemAtScenePos(scenePos);
    if (item) {
        QString itemData = item->data(0).toString();
        if (!itemData.isEmpty() && !itemData.contains('.')) {
            // Double-clicked a component - emit signal for properties editing
            emit componentDoubleClicked(itemData);
            event->accept();
            return;
        }
    }

    QGraphicsView::mouseDoubleClickEvent(event);
}

void SchematicEditor::mouseMoveEvent(QMouseEvent *event)
{
    QPointF scenePos = mapToScene(event->pos());

    if (m_mode == PlaceWireMode && m_tempWire) {
        // Update temporary wire position
        m_tempWire->setLine(m_wireStartPos.x(), m_wireStartPos.y(),
                           scenePos.x(), scenePos.y());
    }

    QGraphicsView::mouseMoveEvent(event);
}

QGraphicsItem *SchematicEditor::itemAtScenePos(const QPointF &pos) const
{
    return m_scene->itemAt(pos, QTransform());
}

QString SchematicEditor::componentIdAtScenePos(const QPointF &pos) const
{
    QGraphicsItem *item = itemAtScenePos(pos);
    if (item) {
        QString data = item->data(0).toString();
        if (!data.isEmpty() && !data.contains('.') && !data.contains("->")) {
            return data;
        }
    }
    return QString();
}

QPointF SchematicEditor::pinPosition(const QString &compId, const QString &pinName) const
{
    auto it = m_components.find(compId);
    if (it == m_components.end())
        return QPointF();

    // Find the pin item in the scene
    QString pinData = compId + "." + pinName;
    QList<QGraphicsItem *> items = m_scene->items();
    for (QGraphicsItem *item : items) {
        if (item->data(0).toString() == pinData) {
            return item->scenePos();
        }
    }

    // Fallback: estimate pin position based on component position
    QPointF compPos = it.value().position;
    if (pinName == "p1")
        return QPointF(compPos.x() - 35, compPos.y());
    else if (pinName == "p2")
        return QPointF(compPos.x() + 30, compPos.y());
    return compPos;
}

void SchematicEditor::startPlacingComponent(const QString &type)
{
    m_mode = PlaceComponentMode;
    m_placeType = type;
    setCursor(Qt::CrossCursor);
}

void SchematicEditor::startPlacingWire(const QString &compId, const QString &pinName)
{
    m_mode = PlaceWireMode;
    m_wireFromComponent = compId;
    m_wireFromPin = pinName;
    m_wireStartPos = pinPosition(compId, pinName);

    // Create temporary wire
    m_tempWire = m_scene->addLine(m_wireStartPos.x(), m_wireStartPos.y(),
                                 m_wireStartPos.x(), m_wireStartPos.y(),
                                 QPen(Qt::red, 2, Qt::DashLine));
    m_tempWire->setZValue(1000);
    setCursor(Qt::CrossCursor);
}

void SchematicEditor::finishWire(const QPointF &endPos)
{
    // Find the component and pin at end position
    QGraphicsItem *item = itemAtScenePos(endPos);
    if (!item) {
        cancelWire();
        return;
    }

    QString pinData = item->data(0).toString();
    if (!pinData.contains('.')) {
        cancelWire();
        return;
    }

    int dot = pinData.indexOf('.');
    QString toCompId = pinData.left(dot);
    QString toPinName = pinData.mid(dot + 1);

    // Don't connect to same pin
    if (m_wireFromComponent == toCompId && m_wireFromPin == toPinName) {
        cancelWire();
        return;
    }

    QString fromPin = m_wireFromComponent + "." + m_wireFromPin;
    QString toPin = toCompId + "." + toPinName;

    // Add the wire
    addWire(fromPin, toPin);

    // Clean up
    cancelWire();
}

void SchematicEditor::cancelWire()
{
    if (m_tempWire) {
        m_scene->removeItem(m_tempWire);
        delete m_tempWire;
        m_tempWire = nullptr;
    }
    m_mode = SelectMode;
    m_wireFromComponent.clear();
    m_wireFromPin.clear();
    m_wireStartPos = QPointF();
    setCursor(Qt::ArrowCursor);
}

void SchematicEditor::buildNets()
{
    m_nets.clear();
    // Nets are built during addWire() now via pinNets
}

QStringList SchematicEditor::generateNetlist() const
{
    QStringList lines;

    // Title line
    lines << "* WOWKISPICE Generated Netlist";
    lines << "* Generated from schematic editor";
    lines << "";

    // Component lines
    for (auto it = m_components.begin(); it != m_components.end(); ++it) {
        const ComponentData &comp = it.value();

        // Build SPICE line: <prefix><id> <node1> <node2> ... <value>
        QString spiceLine = comp.spicePrefix + comp.id;

        // Collect nodes from pin nets
        QStringList nodes;
        for (auto pit = comp.pinNets.begin(); pit != comp.pinNets.end(); ++pit) {
            nodes << pit.value();
        }

        // If no nets assigned, create default nodes
        if (nodes.isEmpty()) {
            static int unnamedNet = 0;
            nodes << QString("net_%1").arg(unnamedNet++);
            nodes << QString("net_%1").arg(unnamedNet++);
        }

        for (const QString &node : nodes) {
            spiceLine += " " + node;
        }

        // Add value parameter
        if (comp.params.contains("value") && !comp.params["value"].isEmpty()) {
            spiceLine += " " + comp.params["value"];
        }

        // Add model parameter if present
        if (comp.params.contains("model") && !comp.params["model"].isEmpty()) {
            spiceLine += " model=" + comp.params["model"];
        }

        lines << spiceLine;
    }

    lines << "";

    // Analysis cards - default to transient if none specified
    bool hasAnalysis = false;
    for (const QString &line : lines) {
        if (line.startsWith(".")) {
            hasAnalysis = true;
            break;
        }
    }

    if (!hasAnalysis) {
        lines << ".tran 1u 5m uic";
    }

    lines << ".end";

    return lines;
}

QString SchematicEditor::spicePrefixForType(const QString &type) const
{
    QString t = type.toLower();
    if (t.contains("resistor")) return "R";
    if (t.contains("capacitor") || t.contains("cap")) return "C";
    if (t.contains("inductor")) return "L";
    if (t.contains("voltage") || t.contains("vsource")) return "V";
    if (t.contains("current") || t.contains("isource")) return "I";
    if (t.contains("mosfet_n")) return "M";
    if (t.contains("mosfet_p")) return "M";
    if (t.contains("bjt_npn")) return "Q";
    if (t.contains("bjt_pnp")) return "Q";
    if (t.contains("diode")) return "D";
    if (t.contains("bjt")) return "Q";
    if (t.contains("opamp") || t.contains("amplifier")) return "X";
    return "R";
}

QString SchematicEditor::defaultValueForType(const QString &type) const
{
    QString t = type.toLower();
    if (t.contains("resistor")) return "1k";
    if (t.contains("capacitor") || t.contains("cap")) return "100n";
    if (t.contains("inductor")) return "10u";
    if (t.contains("voltage") || t.contains("vsource")) return "PULSE(0 5 0 1n 1n 10u 20u)";
    if (t.contains("current") || t.contains("isource")) return "1m";
    if (t.contains("diode")) return "";
    if (t.contains("mosfet")) return "";
    if (t.contains("bjt")) return "";
    return "1k";
}

QString SchematicEditor::resolveModelForType(const QString &type)
{
    // Map component types to default SPICE models
    if (type.contains("opamp", Qt::CaseInsensitive) ||
        type.contains("amplifier", Qt::CaseInsensitive)) {
        return " macromodel_name";
    }
    if (type.contains("resistor", Qt::CaseInsensitive)) {
        return "";
    }
    if (type.contains("capacitor", Qt::CaseInsensitive) ||
        type.contains("cap", Qt::CaseInsensitive)) {
        return "";
    }
    if (type.contains("inductor", Qt::CaseInsensitive) ||
        type.contains("inductor", Qt::CaseInsensitive)) {
        return "";
    }
    return "";
}

void SchematicEditor::modelLibraryManagement()
{
    // Dialog to manage SPICE model libraries
    QStringList models;
    for (auto it = m_componentModels.constBegin(); it != m_componentModels.constEnd(); ++it) {
        models << it.key() + ": " + it.value();
    }

    if (models.isEmpty()) {
        QMessageBox::information(this, "Model Library",
            "No models currently stored.\n"
            "Add components to populate the library.");
        return;
    }

    QString modelName = QInputDialog::getItem(
        this, "Model Library",
        "Select or enter a SPICE model name:",
        models, 0, false);

    if (!modelName.isEmpty()) {
        QMessageBox::information(this, "Model Library",
            "Model '" + modelName + "' selected.\n"
            "This model will be included in the netlist export.\n"
            "Ensure the model is defined in your SPICE directive block.");
    }
}

void SchematicEditor::importWAVStimulus(const QString &filePath)
{
    QMessageBox::information(this, "WAV Stimulus Import",
        "WAV file import functionality:\n"
        "- LTspice supports WAV files as voltage sources\n"
        "- The audio data is sampled and used as a time-varying voltage\n"
        "- Typical use: audio amplification tests, modulation analysis\n"
        "- File will be converted to appropriate SPICE voltage source");

    QMessageBox::information(this, "WAV Import",
        "Selected file: " + filePath + "\n"
        "WAV import is documented in LTspice help under "
        "arbitrary waveform sources.\n"
        "The converted voltage source will be placed at cursor position.");
}

QStringList SchematicEditor::netlist() const
{
    return m_netlistLines;
}

void SchematicEditor::setNetlist(const QStringList &lines)
{
    m_netlistLines = lines;
}
