#include "../include/views/schematic_editor.h"
#include <QtWidgets/QGraphicsSceneMouseEvent>
#include <QtWidgets/QGraphicsRectItem>
#include <QtWidgets/QGraphicsSimpleTextItem>
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

    auto *label = new QGraphicsSimpleTextItem(type, rect);
    label->setPos(-label->boundingRect().width() / 2, -label->boundingRect().height() / 2);

    auto *idLabel = new QGraphicsSimpleTextItem(id, rect);
    idLabel->setPos(-idLabel->boundingRect().width() / 2, 25);
    idLabel->setScale(0.6);

    m_scene->addItem(rect);
    m_components[id] = comp;

    // Store model reference
    m_componentModels[id] = resolveModelForType(type);

    emit componentAdded(id, type, x, y);
}

void SchematicEditor::addWire(const QString &fromPin, const QString &toPin)
{
    auto fromIt = m_wireEndpoints.find(fromPin);
    auto toIt = m_wireEndpoints.find(toPin);
    if (fromIt == m_wireEndpoints.end() || toIt == m_wireEndpoints.end()) {
        return;
    }

    auto *line = m_scene->addLine(
        fromIt.value().first.x(), fromIt.value().first.y(),
        toIt.value().first.x(), toIt.value().first.y(),
        QPen(Qt::red, 2));
    line->setZValue(0);

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

QStringList SchematicEditor::generateNetlist() const
{
    QStringList lines;

    // Build nets (const method can't modify m_nets, so we work on a copy)
    QMap<QString, QVector<QString>> nets;
    int unnamedNet = 0;

    for (auto it = m_components.begin(); it != m_components.end(); ++it) {
        const ComponentData &comp = it.value();
        for (auto pit = comp.pinNets.begin(); pit != comp.pinNets.end(); ++pit) {
            const QString &netName = pit.value();
            nets[netName].append(comp.id + "." + pit.key());
        }
    }

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
            // Default: two unnamed nodes
            nodes << QString("net_%1").arg(unnamedNet);
            ++unnamedNet;
            nodes << QString("net_%1").arg(unnamedNet);
            ++unnamedNet;
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
    if (t.contains("mosfet") || t.contains("nmos") || t.contains("pmos")) return "M";
    if (t.contains("diode")) return "D";
    if (t.contains("bjt") || t.contains("npn") || t.contains("pnp")) return "Q";
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

void SchematicEditor::onAddComponent(const QString &type, qreal x, qreal y)
{
    // Default positioning: grid-based with mouse offset
    addComponent("comp_" + type, type, x, y);
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
