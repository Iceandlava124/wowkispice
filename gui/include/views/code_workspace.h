#ifndef CODE_WORKSPACE_H
#define CODE_WORKSPACE_H

#include <QtWidgets/QWidget>
#include <QtWidgets/QPlainTextEdit>
#include <QtWidgets/QPushButton>
#include <QtWidgets/QVBoxLayout>
#include <QtWidgets/QHBoxLayout>
#include <QtWidgets/QLabel>
#include <QtCore/QString>

class CodeWorkspace : public QWidget {
    Q_OBJECT
public:
    explicit CodeWorkspace(QWidget *parent = nullptr);
    ~CodeWorkspace() override = default;

    void setCode(const QString &code);
    QString code() const;
    void setReadOnly(bool readOnly);

public:
    void runCode();
    void stopCode();
    void clearCode();

private:
    QPlainTextEdit *m_editor = nullptr;
    QPushButton *m_runBtn = nullptr;
    QPushButton *m_stopBtn = nullptr;
    QPushButton *m_clearBtn = nullptr;
    QLabel *m_statusLabel = nullptr;
};

#endif // CODE_WORKSPACE_H
