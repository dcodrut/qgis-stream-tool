from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence, QColor
from PyQt5.QtWidgets import QShortcut, QMessageBox
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsMessageLog,
    QgsProject,
    QgsLayerTreeGroup,
)
from qgis.gui import QgsMapTool, QgsRubberBand


# TODO:
#  - Handle Z values in geometry
#  - Handle CRS differences between layer and map canvas
#  - Check if layer is editable & feature is selected
#  - Check behavior when adding a new feature (e.g. IDs)
#  - Investigate reshape issues with intersection points
#  - Show intersection points for the next segment
#  - Add a shortcut to save edits
#  - Ensure polygon layer is selected before starting
#  - Ensure edits are enabled in reshape mode
#  - Consider creating a QGIS plugin for this tool

def _warn(message):
    QgsMessageLog.logMessage(message, "StreamTool", level=Qgis.Warning)


def _info(message):
    QgsMessageLog.logMessage(message, "StreamTool", level=Qgis.Info)


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

        self.save_shortcut = QShortcut(QKeySequence("S"), self.canvas)
        self.save_shortcut.activated.connect(self._save_edits)

        self.intersection_band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self.intersection_band.setColor(Qt.green)
        self.intersection_band.setWidth(5)

        self.next_shortcut = QShortcut(QKeySequence("]"), self.canvas)
        self.next_shortcut.activated.connect(self._navigate_next)

        self.prev_shortcut = QShortcut(QKeySequence("["), self.canvas)
        self.prev_shortcut.activated.connect(self._navigate_prev)

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.points = []
        self.streaming = False
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
        self.selected_fid = None

        if not self.drawing_mode:
            selected = self.layer.selectedFeatures()
            if len(selected) != 1:
                _warn("Please select exactly one polygon feature (you're in Reshape mode).")
                return
            self.selected_fid = selected[0].id()

        self.mode_toggle.setEnabled(True)
        self.finish_shortcut.setEnabled(True)
        self.space_shortcut.setEnabled(True)
        self.toggle_shortcut.setEnabled(True)
        self.cancel_shortcut.setEnabled(True)
        self.save_shortcut.setEnabled(True)
        self.next_shortcut.setEnabled(True)
        self.prev_shortcut.setEnabled(True)

        self.canvas.setFocus()

    def deactivate(self):
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.finish_shortcut.setEnabled(False)
        self.space_shortcut.setEnabled(False)
        self.toggle_shortcut.setEnabled(False)
        self.cancel_shortcut.setEnabled(False)
        self.mode_toggle.setEnabled(False)
        self.save_shortcut.setEnabled(False)
        self.next_shortcut.setEnabled(False)
        self.prev_shortcut.setEnabled(False)

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
        _info(
            f"Digitizing Mode Toggled. Now in {mode} mode. "
            f"{'Vertices are added every 5m.' if self.stream_enabled else 'Add vertex manually by pressing Space.'}",
        )

    def _cancel(self):
        if not self.points:
            _info("No reshape in progress — exiting tool (ESC pressed).")

            # Exit the edit mode with confirmation
            if self.layer.isEditable():
                if self.layer.isModified():
                    reply = QMessageBox.question(
                        self.canvas,
                        "Save Changes?",
                        "Do you want to save your changes before exiting?",
                        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                        QMessageBox.Save
                    )

                    if reply == QMessageBox.Save:
                        self.layer.commitChanges()
                        _info("Changes saved before exiting.")
                    elif reply == QMessageBox.Discard:
                        self.layer.rollBack()
                        _info("Changes discarded.")
                    else:  # Cancel - don't exit
                        _info("Canceled exit operation.")
                        return
                else:
                    _info("No changes to save before exiting.")
                    self.layer.commitChanges()  # Just for disabling the edit mode

            iface.actionPan().trigger()
        else:
            self.points = []
            self.streaming = False
            self.rubber_band.reset(QgsWkbTypes.LineGeometry)
            self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
            self.intersection_band.reset(QgsWkbTypes.PointGeometry)
            self.canvas.refresh()
            _info("Drawing canceled (ESC pressed).")

    def _toggle_draw_mode(self):
        self.drawing_mode = not self.drawing_mode
        mode = "DRAWING (Contour)" if self.drawing_mode else "RESHAPE"
        _info(f"Mode Switched. You are now in: {mode} mode.")

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
                    _warn("Feature geometry is missing or invalid in _update_rubber_band")
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
            _warn("Draw a reshape line with at least 2 points.")
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
                _info("Polygon feature added.")
            else:
                _warn("Failed to add polygon feature — layer may not be editable or geometry is invalid.")
            if not polygon_geom or not polygon_geom.isGeosValid():
                _warn("Polygon geometry is invalid or empty.")
        else:
            selected = self.layer.selectedFeatures()
            if len(selected) != 1:
                _warn("No feature selected to reshape.")
                self.layer.destroyEditCommand()
                return

            selected_fid = selected[0].id()
            feature = self.layer.getFeature(selected_fid)
            reshape_line = QgsGeometry.fromPolylineXY(self.points)
            feature_geom = feature.geometry()

            # Warn if geometry has Z values
            if QgsWkbTypes.hasZ(feature_geom.wkbType()):
                _warn("Geometry has Z values (3D) — reshaping may not work.")

            if feature_geom.isEmpty() or not feature_geom.isGeosValid():
                _warn("Feature geometry is empty or invalid.")
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
                _warn("Reshape failed. Ensure the line crosses the polygon boundary.")
                self.layer.destroyEditCommand()
                return

            self.layer.changeGeometry(selected_fid, feature_geom)
            _info("Polygon successfully reshaped.")

        self.layer.endEditCommand()
        self.points = []
        self.streaming = False
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
        self.intersection_band.reset(QgsWkbTypes.PointGeometry)
        self.canvas.refresh()

    def _navigate(self, where_to="next"):
        if self.points:  # Reshape in progress; do nothing.
            _warn("Navigation disabled - a reshape is in progress.")
            return

        feature_list = [f for f in self.layer.getFeatures()]
        if not feature_list:
            _warn("No features found in the layer.")
            return

        current_feature = None
        selected = self.layer.selectedFeatures()
        if selected:
            current_feature = selected[0]

        # Find the index of currently selected feature.
        idx = 0
        if current_feature:
            for i, feat in enumerate(feature_list):
                if feat.id() == current_feature.id():
                    _info(f"Current feature ID: {current_feature.id()}")
                    idx = i
                    break

        # Navigate to next/prev (wrap around if needed).
        if where_to == "next":
            if idx == len(feature_list) - 1:
                _info("Reached the last feature. Wrapping to the first.")
                next_idx = 0
            else:
                next_idx = idx + 1
        elif where_to == "prev":
            if idx == 0:
                _info("Reached the first feature. Wrapping to the last.")
                next_idx = len(feature_list) - 1
            else:
                next_idx = idx - 1
        _info(f"Next feature ID: {feature_list[next_idx].id()}")
        next_feature = feature_list[next_idx]

        # Deselect current polygon.
        self.layer.removeSelection()

        self.layer.selectByIds([next_feature.id()])

        # Zoom to extent + 20% buffer
        bbox = next_feature.geometry().boundingBox()  # Get original bounding box
        buffer_factor = 0.2  # 20% of width/height
        width = bbox.width() * buffer_factor
        height = bbox.height() * buffer_factor
        buffered_bbox = bbox.buffered(max(width, height))

        self.canvas.setExtent(buffered_bbox)  # Set canvas extent to buffered bounding box

        self.canvas.refresh()
        _info("Navigated to next feature.")

    def _navigate_next(self):
        _info("Navigating to next feature.")
        self._navigate("next")

    def _navigate_prev(self):
        _info("Navigating to previous feature.")
        self._navigate("prev")

    def _save_edits(self):
        if not self.layer.isEditable():
            _warn("Layer is not editable.")
            return
        if self.layer.commitChanges():
            _info("Edits saved successfully.")

            # Use a timer to toggle editing back on after a short delay & re-enable the edit mode.
            QTimer.singleShot(100, self._restart_editing)  # 100ms delay
        else:
            _warn("Failed to save edits.")

    def _restart_editing(self):
        if not self.layer.isEditable():
            self.layer.startEditing()
            _info("Editing mode re-enabled.")

            self.canvas.refresh()


# Stop previous tool if needed
try:
    _info("Stopping previous tool...")
    iface.actionPan().trigger()
    del reshape_tool
except Exception:
    pass

# Start new reshape tool
reshape_tool = StreamReshapeTool(iface.mapCanvas())
iface.mapCanvas().setMapTool(reshape_tool)
_info("StreamReshapeTool activated.")
