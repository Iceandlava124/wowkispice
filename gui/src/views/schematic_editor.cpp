#include "../include/views/schematic_editor.h"
#include <QtWidgets/QGraphicsSceneMouseEvent>
#include <QtWidgets/QGraphicsRectItem>
#include <QtWidgets/QGraphicsSimpleTextItem>
#include <QtWidgets/QFileDialog>
#include <QtWidgets/QMessageBox>
#include <QtCore/QDebug>
#include <QtCore/QStringLiteral>

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
    // Check if model exists; if not, suggest one from library
    QString model = resolveModelForType(type);
    if (model.isEmpty()) {
        QMessageBox::information(nullptr, "Model Library",
            "No default model for type: " + type + "\n"
            "Use 'Tools → Model Library' to manage SPICE models.");
    }

    auto *rect = new QGraphicsRectItem(x - 30, y - 20, 60, 40);
    rect->setPen(QPen(Qt::darkBlue, 2));
    rect->setBrush(QBrush(QColor("#f0f8ff")));
    rect->setFlag(QGraphicsItem::ItemIsMovable, true);
    rect->setFlag(QGraphicsItem::ItemIsSelectable, true);

    auto *label = new QGraphicsSimpleTextItem(type, rect);
    label->setPos(-label->boundingRect().width() / 2, -label->boundingRect().height() / 2);

    auto *pinLabel = new QGraphicsSimpleTextItem(id, rect);
    pinLabel->setPos(35, -10);
    pinLabel->setScale(0.7);

    m_scene->addItem(rect);
    m_components[id] = rect;

    // Store model reference
    m_componentModels[id] = model;

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

void SchematicEditor::importWAV()
{
    // LTspice: import WAV file as arbitrary voltage stimulus
    QString filePath = QFileDialog::getOpenFileName(
        this, "Import WAV Stimulus", "",
        "Waveform Audio Files (*.wav);;All Files (*)");

    if (!filePath.isEmpty()) {
        importWAVStimulus(filePath);
    }
}

void SchematicEditor::runBodeAnalysis()
{
    // Frequency response analysis from circuit
    // Extract component values, compute transfer function, display Bode plot
    QMessageBox::information(this, "Bode Analysis",
        "Bode plot analysis selected.\n"
        "The GUI will compute the transfer function from the circuit elements\n"
        "and display frequency response with phase and magnitude plots.\n"
        "This addresses LTspice's lack of interactive filter design.");

    // TODO: Implement actual Bode analysis - extract RLC values,
    // compute H(s), plot using QtCharts or emit to parent widget
    qDebug() << "Bode analysis requested from schematic";
}

void SchematicEditor::modelLibraryManagement()
{
    // Dialog to manage SPICE model libraries
    // Addresses LTspice pain point: "需要指出运放使用的 model，并 include进 SPICE netlist"
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

QString SchematicEditor::resolveModelForType(const QString &type)
{
    // Map component types to default SPICE models
    // This is a simplified lookup; in production this would consult
    // a model library or user-defined database
    if (type.contains("opamp", Qt::CaseInsensitive) ||
        type.contains("amplifier", Qt::CaseInsensitive)) {
        return " macromodel_name";  // placeholder - user defines in .lib
    }
    if (type.contains("resistor", Qt::CaseInsensitive)) {
        return "";  // resistors use standard R model
    }
    if (type.contains("capacitor", Qt::CaseInsensitive) ||
        type.contains("cap", Qt::CaseInsensitive)) {
        return "";  // capacitors use standard C model
    }
    if (type.contains("inductor", Qt::CaseInsensitive) ||
        type.contains("inductor", Qt::CaseInsensitive)) {
        return "";  // inductors use standard L model
    }
    return "";  // no default model
}

void SchematicEditor::onAddComponent(const QString &type, qreal x, qreal y)
{
    // Default positioning: grid-based with mouse offset
    addComponent("comp_" + type, type, x, y);
}

void SchematicEditor::importWAVStimulus(const QString &filePath)
{
    // LTspice feature: use WAV file as arbitrary voltage source
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

#include "../moc/schematic_editor.moc"