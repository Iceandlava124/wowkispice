#include "../include/views/code_workspace.h"
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QFileDialog>
#include <QtCore/QFile>
#include <QtCore/QTextStream>
#include <QtCore/QDebug>

CodeWorkspace::CodeWorkspace(QWidget *parent)
    : QWidget(parent)
{
    auto *layout = new QVBoxLayout(this);

    // Editor
    m_editor = new QPlainTextEdit(this);
    m_editor->setPlaceholderText("// Enter simulation control code here...\n"
                                 "// Example:\n"
                                 "// run_sim(tstep=0.5u, duration=5m);\n"
                                 "// set_vin(12.0);\n"
                                 "// probe_v(\"vout\");\n");
    m_editor->setTabStopDistance(40);
    layout->addWidget(m_editor);

    // Button bar
    auto *btnLayout = new QHBoxLayout();
    m_runBtn = new QPushButton("Run Code");
    m_stopBtn = new QPushButton("Stop");
    m_stopBtn->setEnabled(false);
    m_clearBtn = new QPushButton("Clear");

    btnLayout->addWidget(m_runBtn);
    btnLayout->addWidget(m_stopBtn);
    btnLayout->addWidget(m_clearBtn);
    btnLayout->addStretch();

    layout->addLayout(btnLayout);

    // Status
    m_statusLabel = new QLabel("Ready");
    m_statusLabel->setStyleSheet("QLabel { font-weight: bold; color: #4caf50; }");
    layout->addWidget(m_statusLabel);

    connect(m_runBtn, &QPushButton::clicked, this, &CodeWorkspace::runCode);
    connect(m_stopBtn, &QPushButton::clicked, this, &CodeWorkspace::stopCode);
    connect(m_clearBtn, &QPushButton::clicked, this, &CodeWorkspace::clearCode);
}

void CodeWorkspace::setCode(const QString &code)
{
    m_editor->setPlainText(code);
}

QString CodeWorkspace::code() const
{
    return m_editor->toPlainText();
}

void CodeWorkspace::setReadOnly(bool readOnly)
{
    m_editor->setReadOnly(readOnly);
}

void CodeWorkspace::runCode()
{
    m_runBtn->setEnabled(false);
    m_stopBtn->setEnabled(true);
    m_statusLabel->setText("Status: Running...");
    m_statusLabel->setStyleSheet("QLabel { font-weight: bold; color: #ff9800; }");

    // In a full implementation, this would send the code to the Rust backend
    // for execution via the FFI cosim_runner interface
    qDebug() << "Running code:" << m_editor->toPlainText().left(100);
}

void CodeWorkspace::stopCode()
{
    m_runBtn->setEnabled(true);
    m_stopBtn->setEnabled(false);
    m_statusLabel->setText("Status: Stopped");
    m_statusLabel->setStyleSheet("QLabel { font-weight: bold; color: #f44336; }");
}

void CodeWorkspace::clearCode()
{
    m_editor->clear();
    m_statusLabel->setText("Status: Cleared");
}
