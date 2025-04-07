from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QColor
from PyQt5.QtWidgets import QShortcut
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsMessageLog
)
from qgis.gui import QgsMapTool, QgsRubberBand

# TODO:
#  - Add functionality to handle Z values in geometry
#  - Add functionality to handle the difference in the CRS of the layer and the map canvas
#  - Refactor the log messages
#  - (maybe) create a QGIS plugin for this tool


class StreamReshapeTool(QgsMapTool):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.layer = iface.activeLayer()  # iface assumed to be available in QGIS environment
        self.points = []
        self.streaming = False
        self.tolerance = 5
        self.current_cursor_pos = None
        self.selected_fid = None

        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)

        self.preview_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.preview_band.setColor(Qt.blue)
        fill_color = QColor(0, 0, 255, 100)  # blue fill with transparency
        self.preview_band.setFillColor(fill_color)
        self.preview_band.setWidth(2)

        self.finish_shortcut = QShortcut(QKeySequence("Return"), self.canvas)
        self.finish_shortcut.activated.connect(self._finish_reshape)
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self.canvas)
        self.space_shortcut.activated.connect(self._add_vertex_from_cursor)

        self.stream_enabled = False  # Streaming disabled by default

        self.toggle_shortcut = QShortcut(QKeySequence("R"), self.canvas)
        self.toggle_shortcut.activated.connect(self._toggle_stream_mode)

        self.drawing_mode = False  # False = Reshape mode, True = Drawing mode

        self.mode_toggle = QShortcut(QKeySequence("Y"), self.canvas)
        self.mode_toggle.activated.connect(self._toggle_draw_mode)

        self.cancel_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self.canvas)
        self.cancel_shortcut.activated.connect(self._cancel)

        self.intersection_band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self.intersection_band.setColor(Qt.green)
        self.intersection_band.setWidth(5)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.canvas.setFocus()
        self.points = []
        self.streaming = False
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
        self.selected_fid = None

        if not self.drawing_mode:
            selected = self.layer.selectedFeatures()
            if len(selected) != 1:
                QgsMessageLog.logMessage(
                    "Please select exactly one polygon feature. StreamTool",
                    "StreamTool",
                    level=Qgis.Warning
                )
                return
            self.selected_fid = selected[0].id()

        self.canvas.setFocus()
        self.mode_toggle.setEnabled(True)
        self.finish_shortcut.setEnabled(True)
        self.space_shortcut.setEnabled(True)
        self.toggle_shortcut.setEnabled(True)
        self.cancel_shortcut.setEnabled(True)

    def deactivate(self):
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.finish_shortcut.setEnabled(False)
        self.space_shortcut.setEnabled(False)
        self.toggle_shortcut.setEnabled(False)
        self.cancel_shortcut.setEnabled(False)
        self.mode_toggle.setEnabled(False)
        super().deactivate()

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            if not self.streaming or not self.points:
                self.points = [pt]
                self.streaming = True
                self.rubber_band.reset(QgsWkbTypes.LineGeometry)
                self.rubber_band.addPoint(pt)
            else:
                self.points.append(pt)
                self._update_rubber_band()

    def canvasMoveEvent(self, event):
        if not self.points:
            return
        self.current_cursor_pos = self.toMapCoordinates(event.pos())
        if self.streaming and self.stream_enabled:
            last = self.points[-1]
            if last.distance(self.current_cursor_pos) >= self.tolerance:
                self.points.append(self.current_cursor_pos)
        self._update_rubber_band()

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            pt = self.toMapCoordinates(event.pos())
            self.points.append(pt)
            self._update_rubber_band()
            self._finish_reshape()

    def _toggle_stream_mode(self):
        self.stream_enabled = not self.stream_enabled
        mode = "STREAMING" if self.stream_enabled else "MANUAL"
        QgsMessageLog.logMessage(
            f"Digitizing Mode Toggled. Now in {mode} mode. "
            f"{'Auto add every 5m' if self.stream_enabled else 'Add vertex manually with Space'}",
            "StreamTool",
            level=Qgis.Info
        )

    def _cancel(self):
        if not self.points:
            QgsMessageLog.logMessage("No reshape in progress — exiting tool (ESC pressed).", "StreamTool", Qgis.Info)
            iface.actionPan().trigger()
        else:
            self.points = []
            self.streaming = False
            self.rubber_band.reset(QgsWkbTypes.LineGeometry)
            self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
            self.intersection_band.reset(QgsWkbTypes.PointGeometry)
            self.canvas.refresh()
            QgsMessageLog.logMessage("Drawing canceled (ESC pressed)", "StreamTool", Qgis.Info)

    def _toggle_draw_mode(self):
        self.drawing_mode = not self.drawing_mode
        mode = "DRAWING (Contour)" if self.drawing_mode else "RESHAPE"
        QgsMessageLog.logMessage(f"Mode Switched. You are now in: {mode} mode.", "StreamTool", Qgis.Info)

    def _add_vertex_from_cursor(self):
        if self.streaming and self.current_cursor_pos:
            self.points.append(self.current_cursor_pos)
            self._update_rubber_band()

    def _update_rubber_band(self):
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        for pt in self.points:
            self.rubber_band.addPoint(pt)

        if self.current_cursor_pos:
            preview_points = self.points + [self.current_cursor_pos]
            if preview_points and preview_points[0] != preview_points[-1]:
                preview_points.append(preview_points[0])
            polygon = QgsGeometry.fromPolygonXY([preview_points])
            self.preview_band.setToGeometry(polygon, None)
        else:
            self.preview_band.reset(QgsWkbTypes.PolygonGeometry)

        self.intersection_band.reset(QgsWkbTypes.PointGeometry)

        if not self.drawing_mode and self.points and len(self.points) >= 2:
            selected = self.layer.selectedFeatures()
            if len(selected) == 1:
                feature = selected[0]
                geom = feature.geometry()
                if not geom or geom.isEmpty() or not geom.isGeosValid():
                    QgsMessageLog.logMessage(
                        "Feature geometry is missing or invalid in _update_rubber_band",
                        "StreamTool",
                        Qgis.Warning
                    )
                    return
                reshape_line = QgsGeometry.fromPolylineXY(self.points)
                boundary_geom = QgsGeometry(geom.constGet().boundary())
                intersection = boundary_geom.intersection(reshape_line)
                self.intersection_band.reset(QgsWkbTypes.PointGeometry)
                if intersection and intersection.wkbType() == QgsWkbTypes.MultiPoint:
                    for pt in intersection.asMultiPoint():
                        self.intersection_band.addPoint(pt)
                elif intersection and intersection.wkbType() == QgsWkbTypes.Point:
                    self.intersection_band.addPoint(intersection.asPoint())

    def _finish_reshape(self):
        if not self.streaming or len(self.points) < 2:
            QgsMessageLog.logMessage("Draw a reshape line with at least 2 points.", "StreamTool", Qgis.Warning)
            return

        self.layer.beginEditCommand("Stream Edit")
        if self.drawing_mode:
            ring = self.points + [self.points[0]]
            polygon_geom = QgsGeometry.fromPolygonXY([ring])
            feature = QgsFeature(self.layer.fields())
            feature.setGeometry(polygon_geom)
            success = self.layer.addFeature(feature)
            self.canvas.refresh()
            if success:
                QgsMessageLog.logMessage("Polygon feature added.", "StreamTool", Qgis.Info)
            else:
                QgsMessageLog.logMessage(
                    "Failed to add polygon feature — layer may not be editable or geometry is invalid.",
                    "StreamTool",
                    Qgis.Warning
                )
            if not polygon_geom or not polygon_geom.isGeosValid():
                QgsMessageLog.logMessage("Polygon geometry is invalid or empty.", "StreamTool", Qgis.Warning)
        else:
            selected = self.layer.selectedFeatures()
            if len(selected) != 1:
                QgsMessageLog.logMessage("No feature selected to reshape.", "StreamTool", Qgis.Warning)
                self.layer.destroyEditCommand()
                return

            selected_fid = selected[0].id()
            feature = self.layer.getFeature(selected_fid)
            reshape_line = QgsGeometry.fromPolylineXY(self.points)
            feature_geom = feature.geometry()

            # Warn if geometry has Z values
            if QgsWkbTypes.hasZ(feature_geom.wkbType()):
                QgsMessageLog.logMessage("Geometry has Z values (3D) — reshaping may not work.", "StreamTool",
                                         Qgis.Warning)

            if feature_geom.isEmpty() or not feature_geom.isGeosValid():
                QgsMessageLog.logMessage("Feature geometry is empty or invalid.", "StreamTool", Qgis.Warning)
                self.layer.destroyEditCommand()
                return

            boundary_geom = QgsGeometry(feature_geom.constGet().boundary())
            intersection = boundary_geom.intersection(reshape_line)
            self.intersection_band.reset(QgsWkbTypes.PointGeometry)
            if intersection and intersection.wkbType() == QgsWkbTypes.MultiPoint:
                for pt in intersection.asMultiPoint():
                    self.intersection_band.addPoint(pt)
            elif intersection and intersection.wkbType() == QgsWkbTypes.Point:
                self.intersection_band.addPoint(intersection.asPoint())

            status = feature_geom.reshapeGeometry(reshape_line.constGet())
            if status != QgsGeometry.OperationResult.Success:
                QgsMessageLog.logMessage(
                    "Reshape failed. Ensure the line crosses the polygon boundary.",
                    "StreamTool",
                    Qgis.Warning
                )
                self.layer.destroyEditCommand()
                return

            self.layer.changeGeometry(selected_fid, feature_geom)
            QgsMessageLog.logMessage("Polygon successfully reshaped.", "StreamTool", Qgis.Info)

        self.layer.endEditCommand()
        self.points = []
        self.streaming = False
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
        self.intersection_band.reset(QgsWkbTypes.PointGeometry)
        self.canvas.refresh()


# Stop previous tool if needed
try:
    iface.actionPan().trigger()
    del reshape_tool
except Exception:
    pass

# Start new reshape tool
reshape_tool = StreamReshapeTool(iface.mapCanvas())
iface.mapCanvas().setMapTool(reshape_tool)
QgsMessageLog.logMessage("StreamReshapeTool activated.", "StreamTool", Qgis.Info)
