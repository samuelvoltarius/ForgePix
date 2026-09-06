"""Browse stored result files and their verified provenance; no fake undo."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from i18n import tr


class ProjectHistoryDialog(QDialog):
    def __init__(self, project, checks, parent=None):
        super().__init__(parent)
        self.project, self.checks = project, checks
        self.selected_step = None
        self.relocate_requested = False
        self.setWindowTitle(tr("Projektverlauf") + " — " + project.data["name"])
        self.resize(850, 590)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        description = QLabel(tr("Gespeicherte Ergebnisstände öffnen. Die Dateien werden geprüft und bleiben unverändert."))
        description.setWordWrap(True)
        layout.addWidget(description)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Ergebnisstand"), tr("Gespeichert"), tr("Dateistatus")])
        self.tree.setRootIsDecorated(False)
        self.tree.setStyleSheet("QTreeWidget { background:#202227; border:1px solid #30343a; "
                                "selection-background-color:#4F7CFF; selection-color:#ffffff; } "
                                "QTreeWidget::item { min-height:28px; padding:2px 5px; } "
                                "QHeaderView::section { background:#26282e; color:#e8eae6; "
                                "border:0; border-bottom:1px solid #34383f; padding:6px; }")
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 165)
        layout.addWidget(self.tree, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 2)
        note = QLabel(tr("Das Projekt speichert Ordner, Modul und Ergebnisstände. Es berechnet keine früheren Schritte neu; Verarbeitungseinstellungen bleiben im Programm."))
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.relocate = QPushButton(tr("Datei neu zuordnen …"))
        self.relocate.setToolTip(tr("Nur eine Datei mit derselben gespeicherten Prüfsumme kann zugeordnet werden."))
        self.relocate.clicked.connect(lambda: self.finish(True))
        actions.addWidget(self.relocate)
        actions.addStretch()
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.open_button = QPushButton(tr("Ergebnis öffnen"))
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(lambda: self.finish(False))
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        for number, step in enumerate(project.data["steps"], 1):
            status = checks[step["id"]]
            intact = status["result"]["status"] == "ok" and all(x["status"] == "ok" for x in status["artifacts"])
            text = tr("Sicherung unverändert") if intact else tr("Datei fehlt oder verändert")
            if intact and status["origin"]["status"] != "ok":
                text += " · " + tr("Original fehlt oder verändert")
            if intact and status.get("comparison", {}).get("status", "ok") != "ok":
                text += " · " + tr("Vergleich fehlt oder verändert")
            caption = step["label"]
            tasks = {"denoise": tr("Rauschen reduzieren"), "background": tr("Hintergrund ausgleichen"),
                     "deblur": tr("Unschärfe reduzieren"), "starless": tr("Sterne entfernen")}
            if step["details"].get("task") in tasks:
                caption = tasks[step["details"]["task"]]
                strength = step["details"].get("strength")
                if type(strength) in (int, float) and 0 <= strength <= 1:
                    caption += " · %.0f %%" % (strength * 100)
            caption += " · " + Path(status["origin"]["path"]).name
            item = QTreeWidgetItem([f"{number}. {caption}", step["created"].replace("T", " ")[:19] + " UTC", text])
            item.setToolTip(0, caption)
            item.setToolTip(2, text)
            item.setData(0, Qt.UserRole, step["id"])
            self.tree.addTopLevelItem(item)
            if step["id"] == project.data.get("selected_step"):
                self.tree.setCurrentItem(item)
        self.tree.currentItemChanged.connect(self.refresh)
        self.tree.itemDoubleClicked.connect(lambda *_: self.finish(False) if self.open_button.isEnabled() else None)
        if not self.tree.currentItem() and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(self.tree.topLevelItemCount() - 1))
        self.refresh()

    def refresh(self, *_):
        item = self.tree.currentItem()
        self.selected_step = item.data(0, Qt.UserRole) if item else None
        self.relocate.setEnabled(bool(item))
        if not item:
            self.open_button.setEnabled(False)
            self.details.setPlainText(tr("Noch keine Ergebnisstände. Neue fertige Ergebnisse werden im aktiven Projekt automatisch gesichert."))
            return
        step, status = self.project.step(self.selected_step), self.checks[self.selected_step]
        intact = status["result"]["status"] == "ok" and all(x["status"] == "ok" for x in status["artifacts"])
        self.open_button.setEnabled(intact)
        parent = "—"
        for index, previous in enumerate(self.project.data["steps"], 1):
            if previous["id"] == step.get("parent_id"):
                parent = "%d. %s · %s" % (index, previous["label"],
                                          Path(self.checks[previous["id"]]["origin"]["path"]).name)
                break
        lines = [tr("Gesicherte Datei") + ": " + status["result"]["path"],
                 tr("Ursprüngliche Datei") + ": " + status["origin"]["path"],
                 "SHA256: " + step["result"]["sha256"],
                 tr("Vorgänger") + ": " + parent]
        if "comparison" in status:
            lines.append(tr("Vergleichsdatei") + ": " + status["comparison"]["path"])
        status_labels = {"ok": tr("Unverändert"), "changed": tr("Verändert"),
                         "missing": tr("Fehlt"), "unreadable": tr("Nicht lesbar")}
        for artifact in status["artifacts"]:
            lines.append(tr("Begleitdatei") + ": " + Path(artifact["path"]).name + " · " + status_labels[artifact["status"]])
        if step["details"]:
            lines.append(json.dumps(step["details"], indent=2, ensure_ascii=False))
        self.details.setPlainText("\n".join(lines))

    def finish(self, relocate):
        if self.selected_step and (relocate or self.open_button.isEnabled()):
            self.relocate_requested = relocate
            self.accept()
