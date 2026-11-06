#include "mainwindow.h"
#include <QtWidgets/QApplication>

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);
    app.setApplicationName("WOWKISPICE");
    app.setApplicationVersion("0.1.0");
    app.setOrganizationName("WOWKISPICE");
    app.setOrganizationDomain("wowkispice.local");

    MainWindow w;
    w.show();
    return app.exec();
}
