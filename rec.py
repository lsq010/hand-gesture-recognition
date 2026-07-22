# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'rec.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLayout,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(1000, 760)
        Form.setMinimumSize(QSize(860, 560))
        Form.setStyleSheet(u"\n"
"    QWidget {\n"
"      background-color: #0d0d0d;\n"
"      color: #f0f0f0;\n"
"      font-family: \"Microsoft YaHei\", \"SimHei\", sans-serif;\n"
"      font-size: 13px;\n"
"    }\n"
"    QGroupBox {\n"
"      border: 2px dashed #ffffff;\n"
"      border-radius: 6px;\n"
"      margin-top: 10px;\n"
"      padding-top: 8px;\n"
"      padding-bottom: 8px;\n"
"      padding-left: 10px;\n"
"      padding-right: 10px;\n"
"      font-weight: bold;\n"
"      color: #f0f0f0;\n"
"    }\n"
"    QGroupBox::title {\n"
"      subcontrol-origin: margin;\n"
"      subcontrol-position: top left;\n"
"      left: 8px;\n"
"      padding: 0 5px;\n"
"      color: #f0f0f0;\n"
"      background-color: #0d0d0d;\n"
"    }\n"
"    QPushButton {\n"
"      background-color: #1a1a1a;\n"
"      border: 2px dashed #ffffff;\n"
"      border-radius: 5px;\n"
"      padding: 6px 14px;\n"
"      color: #f0f0f0;\n"
"      min-width: 70px;\n"
"    }\n"
"    QPushButton:hover {\n"
"      background-color: #333333;\n"
"    }\n"
"    QPushButto"
                        "n:pressed {\n"
"      background-color: #444444;\n"
"    }\n"
"    QPushButton:disabled {\n"
"      color: #666666;\n"
"      border-color: #555555;\n"
"    }\n"
"    QCheckBox {\n"
"      color: #f0f0f0;\n"
"      spacing: 6px;\n"
"    }\n"
"    QCheckBox::indicator {\n"
"      width: 22px;\n"
"      height: 22px;\n"
"      border: 2px dashed #ffffff;\n"
"      border-radius: 3px;\n"
"      background-color: #1a1a1a;\n"
"      image: none;\n"
"    }\n"
"    QCheckBox::indicator:hover {\n"
"      border-color: #4a9eff;\n"
"    }\n"
"    QCheckBox::indicator:unchecked:hover {\n"
"      background-color: #252525;\n"
"    }\n"
"    QCheckBox::indicator:checked {\n"
"      background-color: #1a1a1a;\n"
"      border: 2px solid #4a9eff;\n"
"      image: url(check.png);\n"
"    }\n"
"    QLabel {\n"
"      color: #f0f0f0;\n"
"      font-family: \"Microsoft YaHei\", \"SimHei\", sans-serif;\n"
"    }\n"
"   ")
        self.mainLayout = QVBoxLayout(Form)
        self.mainLayout.setSpacing(10)
        self.mainLayout.setObjectName(u"mainLayout")
        self.mainLayout.setContentsMargins(14, 14, 14, 10)
        self.titleLabel = QLabel(Form)
        self.titleLabel.setObjectName(u"titleLabel")
        self.titleLabel.setMaximumSize(QSize(16777215, 40))
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        self.titleLabel.setFont(font)
        self.titleLabel.setStyleSheet(u"border: 2px dashed #ffffff; border-radius: 6px; padding: 4px; background-color: #151515;")
        self.titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mainLayout.addWidget(self.titleLabel)

        self.contentLayout = QHBoxLayout()
        self.contentLayout.setSpacing(12)
        self.contentLayout.setObjectName(u"contentLayout")
        self.camFrame = QFrame(Form)
        self.camFrame.setObjectName(u"camFrame")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(2)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.camFrame.sizePolicy().hasHeightForWidth())
        self.camFrame.setSizePolicy(sizePolicy)
        self.camFrame.setStyleSheet(u"QFrame { border: 2px dashed #ffffff; border-radius: 6px; background-color: #151515; }")
        self.camFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.camLayout = QVBoxLayout(self.camFrame)
        self.camLayout.setObjectName(u"camLayout")
        self.camLayout.setContentsMargins(0, 0, 0, 0)
        self.camLabel = QLabel(self.camFrame)
        self.camLabel.setObjectName(u"camLabel")
        font1 = QFont()
        font1.setPointSize(16)
        font1.setBold(True)
        self.camLabel.setFont(font1)
        self.camLabel.setStyleSheet(u"border: none; background-color: transparent; color: #888888;")
        self.camLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.camLayout.addWidget(self.camLabel)


        self.contentLayout.addWidget(self.camFrame)

        self.rightPanelLayout = QVBoxLayout()
        self.rightPanelLayout.setSpacing(8)
        self.rightPanelLayout.setObjectName(u"rightPanelLayout")
        self.rightPanelLayout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.controlGroup = QGroupBox(Form)
        self.controlGroup.setObjectName(u"controlGroup")
        self.controlLayout = QVBoxLayout(self.controlGroup)
        self.controlLayout.setSpacing(8)
        self.controlLayout.setObjectName(u"controlLayout")
        self.openCamButton = QPushButton(self.controlGroup)
        self.openCamButton.setObjectName(u"openCamButton")

        self.controlLayout.addWidget(self.openCamButton)

        self.closeCamButton = QPushButton(self.controlGroup)
        self.closeCamButton.setObjectName(u"closeCamButton")

        self.controlLayout.addWidget(self.closeCamButton)


        self.rightPanelLayout.addWidget(self.controlGroup)

        self.resultGroup = QGroupBox(Form)
        self.resultGroup.setObjectName(u"resultGroup")
        self.resultGroup.setMinimumSize(QSize(0, 300))
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.resultGroup.sizePolicy().hasHeightForWidth())
        self.resultGroup.setSizePolicy(sizePolicy1)
        self.resultLayout = QVBoxLayout(self.resultGroup)
        self.resultLayout.setSpacing(8)
        self.resultLayout.setObjectName(u"resultLayout")
        self.handsColumnsLayout = QHBoxLayout()
        self.handsColumnsLayout.setSpacing(10)
        self.handsColumnsLayout.setObjectName(u"handsColumnsLayout")
        self.leftHandGroup = QGroupBox(self.resultGroup)
        self.leftHandGroup.setObjectName(u"leftHandGroup")
        self.leftHandGroup.setMinimumSize(QSize(0, 150))
        sizePolicy1.setHeightForWidth(self.leftHandGroup.sizePolicy().hasHeightForWidth())
        self.leftHandGroup.setSizePolicy(sizePolicy1)
        self.leftHandFormLayout = QFormLayout(self.leftHandGroup)
        self.leftHandFormLayout.setObjectName(u"leftHandFormLayout")
        self.leftHandFormLayout.setHorizontalSpacing(8)
        self.leftHandFormLayout.setVerticalSpacing(10)
        self.leftGestureLabelTitle = QLabel(self.leftHandGroup)
        self.leftGestureLabelTitle.setObjectName(u"leftGestureLabelTitle")

        self.leftHandFormLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.leftGestureLabelTitle)

        self.leftGestureLabelValue = QLabel(self.leftHandGroup)
        self.leftGestureLabelValue.setObjectName(u"leftGestureLabelValue")
        self.leftGestureLabelValue.setStyleSheet(u"color: #4a9eff; font-weight: bold; font-family: \"Microsoft YaHei\", \"SimHei\", sans-serif;")

        self.leftHandFormLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.leftGestureLabelValue)

        self.leftFingerLabelTitle = QLabel(self.leftHandGroup)
        self.leftFingerLabelTitle.setObjectName(u"leftFingerLabelTitle")

        self.leftHandFormLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.leftFingerLabelTitle)

        self.leftFingerLabelValue = QLabel(self.leftHandGroup)
        self.leftFingerLabelValue.setObjectName(u"leftFingerLabelValue")

        self.leftHandFormLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.leftFingerLabelValue)

        self.leftDirectionLabelTitle = QLabel(self.leftHandGroup)
        self.leftDirectionLabelTitle.setObjectName(u"leftDirectionLabelTitle")

        self.leftHandFormLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.leftDirectionLabelTitle)

        self.leftDirectionLabelValue = QLabel(self.leftHandGroup)
        self.leftDirectionLabelValue.setObjectName(u"leftDirectionLabelValue")

        self.leftHandFormLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.leftDirectionLabelValue)


        self.handsColumnsLayout.addWidget(self.leftHandGroup)

        self.rightHandGroup = QGroupBox(self.resultGroup)
        self.rightHandGroup.setObjectName(u"rightHandGroup")
        self.rightHandGroup.setMinimumSize(QSize(0, 150))
        sizePolicy1.setHeightForWidth(self.rightHandGroup.sizePolicy().hasHeightForWidth())
        self.rightHandGroup.setSizePolicy(sizePolicy1)
        self.rightHandFormLayout = QFormLayout(self.rightHandGroup)
        self.rightHandFormLayout.setObjectName(u"rightHandFormLayout")
        self.rightHandFormLayout.setHorizontalSpacing(8)
        self.rightHandFormLayout.setVerticalSpacing(10)
        self.rightGestureLabelTitle = QLabel(self.rightHandGroup)
        self.rightGestureLabelTitle.setObjectName(u"rightGestureLabelTitle")

        self.rightHandFormLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.rightGestureLabelTitle)

        self.rightGestureLabelValue = QLabel(self.rightHandGroup)
        self.rightGestureLabelValue.setObjectName(u"rightGestureLabelValue")
        self.rightGestureLabelValue.setStyleSheet(u"color: #4a9eff; font-weight: bold; font-family: \"Microsoft YaHei\", \"SimHei\", sans-serif;")

        self.rightHandFormLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.rightGestureLabelValue)

        self.rightFingerLabelTitle = QLabel(self.rightHandGroup)
        self.rightFingerLabelTitle.setObjectName(u"rightFingerLabelTitle")

        self.rightHandFormLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.rightFingerLabelTitle)

        self.rightFingerLabelValue = QLabel(self.rightHandGroup)
        self.rightFingerLabelValue.setObjectName(u"rightFingerLabelValue")

        self.rightHandFormLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.rightFingerLabelValue)

        self.rightDirectionLabelTitle = QLabel(self.rightHandGroup)
        self.rightDirectionLabelTitle.setObjectName(u"rightDirectionLabelTitle")

        self.rightHandFormLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.rightDirectionLabelTitle)

        self.rightDirectionLabelValue = QLabel(self.rightHandGroup)
        self.rightDirectionLabelValue.setObjectName(u"rightDirectionLabelValue")

        self.rightHandFormLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.rightDirectionLabelValue)


        self.handsColumnsLayout.addWidget(self.rightHandGroup)


        self.resultLayout.addLayout(self.handsColumnsLayout)

        self.meaningGroup = QGroupBox(self.resultGroup)
        self.meaningGroup.setObjectName(u"meaningGroup")
        self.meaningGroup.setMinimumSize(QSize(0, 70))
        sizePolicy1.setHeightForWidth(self.meaningGroup.sizePolicy().hasHeightForWidth())
        self.meaningGroup.setSizePolicy(sizePolicy1)
        self.meaningLayout = QVBoxLayout(self.meaningGroup)
        self.meaningLayout.setSpacing(6)
        self.meaningLayout.setObjectName(u"meaningLayout")
        self.meaningLabelValue = QLabel(self.meaningGroup)
        self.meaningLabelValue.setObjectName(u"meaningLabelValue")
        self.meaningLabelValue.setStyleSheet(u"color: #ffd700; font-weight: bold; font-family: \"Microsoft YaHei\", \"SimHei\", sans-serif;")
        self.meaningLabelValue.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meaningLabelValue.setWordWrap(True)

        self.meaningLayout.addWidget(self.meaningLabelValue)


        self.resultLayout.addWidget(self.meaningGroup)


        self.rightPanelLayout.addWidget(self.resultGroup)

        self.displayGroup = QGroupBox(Form)
        self.displayGroup.setObjectName(u"displayGroup")
        self.displayLayout = QVBoxLayout(self.displayGroup)
        self.displayLayout.setSpacing(8)
        self.displayLayout.setObjectName(u"displayLayout")
        self.drawSkeletonCheck = QCheckBox(self.displayGroup)
        self.drawSkeletonCheck.setObjectName(u"drawSkeletonCheck")
        self.drawSkeletonCheck.setChecked(True)

        self.displayLayout.addWidget(self.drawSkeletonCheck)

        self.mirrorCheck = QCheckBox(self.displayGroup)
        self.mirrorCheck.setObjectName(u"mirrorCheck")
        self.mirrorCheck.setChecked(True)

        self.displayLayout.addWidget(self.mirrorCheck)


        self.rightPanelLayout.addWidget(self.displayGroup)

        self.recordGroup = QGroupBox(Form)
        self.recordGroup.setObjectName(u"recordGroup")
        self.recordLayout = QHBoxLayout(self.recordGroup)
        self.recordLayout.setSpacing(10)
        self.recordLayout.setObjectName(u"recordLayout")
        self.screenshotButton = QPushButton(self.recordGroup)
        self.screenshotButton.setObjectName(u"screenshotButton")

        self.recordLayout.addWidget(self.screenshotButton)

        self.saveButton = QPushButton(self.recordGroup)
        self.saveButton.setObjectName(u"saveButton")
        self.saveButton.setEnabled(False)

        self.recordLayout.addWidget(self.saveButton)

        self.exportButton = QPushButton(self.recordGroup)
        self.exportButton.setObjectName(u"exportButton")

        self.recordLayout.addWidget(self.exportButton)


        self.rightPanelLayout.addWidget(self.recordGroup)


        self.contentLayout.addLayout(self.rightPanelLayout)


        self.mainLayout.addLayout(self.contentLayout)

        self.statusBar = QLabel(Form)
        self.statusBar.setObjectName(u"statusBar")
        self.statusBar.setMaximumSize(QSize(16777215, 30))
        font2 = QFont()
        font2.setPointSize(11)
        self.statusBar.setFont(font2)
        self.statusBar.setStyleSheet(u"border: 2px dashed #ffffff; border-radius: 5px; padding: 3px 8px; background-color: #151515; color: #cccccc;")
        self.statusBar.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)

        self.mainLayout.addWidget(self.statusBar)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"AI \u624b\u52bf\u8bc6\u522b\u7cfb\u7edf", None))
        self.titleLabel.setText(QCoreApplication.translate("Form", u"\U0001f44b AI \u624b\u52bf\u8bc6\u522b\u7cfb\u7edf", None))
        self.camLabel.setText(QCoreApplication.translate("Form", u"CAM \u753b\u9762\u5c55\u793a\u533a", None))
        self.controlGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f3ae \u7cfb\u7edf\u63a7\u5236", None))
        self.openCamButton.setText(QCoreApplication.translate("Form", u"\u25b6\ufe0f \u6253\u5f00\u6444\u50cf\u5934", None))
        self.closeCamButton.setText(QCoreApplication.translate("Form", u"\u23f9\ufe0f \u5173\u95ed\u6444\u50cf\u5934", None))
        self.resultGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f4ca \u5b9e\u65f6\u8bc6\u522b\u7ed3\u679c", None))
        self.leftHandGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f448 \u5de6\u624b (Left)", None))
        self.leftGestureLabelTitle.setText(QCoreApplication.translate("Form", u"\u624b\u52bf\uff1a", None))
        self.leftGestureLabelValue.setText(QCoreApplication.translate("Form", u"\u672a\u68c0\u6d4b", None))
        self.leftFingerLabelTitle.setText(QCoreApplication.translate("Form", u"\u624b\u6307\uff1a", None))
        self.leftFingerLabelValue.setText(QCoreApplication.translate("Form", u"\u2014 / 5", None))
        self.leftDirectionLabelTitle.setText(QCoreApplication.translate("Form", u"\u65b9\u5411\uff1a", None))
        self.leftDirectionLabelValue.setText(QCoreApplication.translate("Form", u"\u2014", None))
        self.rightHandGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f449 \u53f3\u624b (Right)", None))
        self.rightGestureLabelTitle.setText(QCoreApplication.translate("Form", u"\u624b\u52bf\uff1a", None))
        self.rightGestureLabelValue.setText(QCoreApplication.translate("Form", u"\u672a\u68c0\u6d4b", None))
        self.rightFingerLabelTitle.setText(QCoreApplication.translate("Form", u"\u624b\u6307\uff1a", None))
        self.rightFingerLabelValue.setText(QCoreApplication.translate("Form", u"\u2014 / 5", None))
        self.rightDirectionLabelTitle.setText(QCoreApplication.translate("Form", u"\u65b9\u5411\uff1a", None))
        self.rightDirectionLabelValue.setText(QCoreApplication.translate("Form", u"\u2014", None))
        self.meaningGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f4a1 \u624b\u52bf\u542b\u4e49", None))
        self.meaningLabelValue.setText(QCoreApplication.translate("Form", u"\u7b49\u5f85\u8bc6\u522b...", None))
        self.displayGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f6e0\ufe0f \u663e\u793a\u8bbe\u7f6e", None))
        self.drawSkeletonCheck.setText(QCoreApplication.translate("Form", u"\u7ed8\u5236\u624b\u90e8\u9aa8\u67b6", None))
        self.mirrorCheck.setText(QCoreApplication.translate("Form", u"\u753b\u9762\u955c\u50cf", None))
        self.recordGroup.setTitle(QCoreApplication.translate("Form", u"\U0001f5c2\ufe0f \u6570\u636e\u8bb0\u5f55", None))
        self.screenshotButton.setText(QCoreApplication.translate("Form", u"\U0001f4f7 \u622a\u56fe", None))
        self.saveButton.setText(QCoreApplication.translate("Form", u"\U0001f4be \u4fdd\u5b58", None))
        self.exportButton.setText(QCoreApplication.translate("Form", u"\U0001f4c1 \u5bfc\u51fa", None))
        self.statusBar.setText(QCoreApplication.translate("Form", u"\u72b6\u6001\u680f\uff1a\u7cfb\u7edf\u5c31\u7eea | FPS: --", None))
    # retranslateUi

