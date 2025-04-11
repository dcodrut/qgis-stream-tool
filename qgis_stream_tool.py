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
#  - Check what happens when multiple features are selected

def _warn(message):
    QgsMessageLog.logMessage(message, "StreamTool", level=Qgis.Warning)


def _info(message):
    QgsMessageLog.logMessage(message, "StreamTool", level=Qgis.Info)


def _debug(message):
    QgsMessageLog.logMessage(f"Debug: {message}", "StreamTool", level=Qgis.Info)


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

        self.repair_shortcut = QShortcut(QKeySequence("F"), self.canvas)
        self.repair_shortcut.activated.connect(self._repair_selected_geometry)

        self.group_keys = {}
        for i in range(10):
            key = str(i)
            shortcut = QShortcut(QKeySequence(key), self.canvas)
            shortcut.activated.connect(lambda n=i: self._switch_group(f"g_{n}"))
            self.group_keys[key] = shortcut

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

        for shortcut in self.group_keys.values():
            shortcut.setEnabled(True)

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

        for shortcut in self.group_keys.values():
            shortcut.setEnabled(False)

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

    def _switch_group(self, group_prefix_to_show):
        root = QgsProject.instance().layerTreeRoot()

        # check if our special group exists
        target_group = root.findGroup('qgis_stream_tool')
        if target_group is None:
            _warn("Group 'qgis_stream_tool' not found.")
            return

        group_name_found = None
        for child in target_group.children():
            if child.name()[:3] == group_prefix_to_show:
                _info(f"Switching to group '{child.name()}'")
                child.setItemVisibilityChecked(True)
                group_name_found = child.name()
            else:
                child.setItemVisibilityChecked(False)

        if group_name_found is None:
            _warn(f"Group with the prefix '{group_prefix_to_show}' not found.")
            return

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

    def _delete_circumvented_feature(self, drawn_polygon):
        """Delete a ring or part that is completely contained within the drawn polygon."""
        selected = self.layer.selectedFeatures()
        if not selected:
            _warn("No feature selected")
            return False

        feature = selected[0]
        geometry = feature.geometry()

        # Local function to check if a ring should be kept
        def should_keep_ring(ring, ring_index=None, part_index=None):
            # Create a proper ring geometry for containment testing
            ring_geom = QgsGeometry.fromPolygonXY([ring])

            # Keep the ring if it's not completely contained in the drawn polygon
            return not drawn_polygon.contains(ring_geom)

        # Local function to process a single polygon (whether standalone or part of multipolygon)
        def process_polygon(polygon, part_index=None):
            exterior_ring = polygon[0]
            rings_to_keep = [exterior_ring]  # Always keep the exterior ring

            # Check each interior ring (hole)
            for i in range(1, len(polygon)):
                ring = polygon[i]
                if should_keep_ring(ring, i, part_index):
                    rings_to_keep.append(ring)

            # Return the processed polygon and whether it was modified
            return rings_to_keep, len(rings_to_keep) < len(polygon)

        # For multi-polygon features
        modified = False
        if QgsWkbTypes.isMultiType(geometry.wkbType()):
            multi_polygon = geometry.asMultiPolygon()
            new_multi_polygon = []

            for i_part, part in enumerate(multi_polygon):
                new_part, part_modified = process_polygon(part, i_part)

                # Only keep parts whose exterior rings aren't contained
                exterior_points = QgsGeometry.fromPolylineXY(part[0])
                if not drawn_polygon.contains(exterior_points):
                    new_multi_polygon.append(new_part)
                    modified = modified or part_modified
                    if part_modified:
                        _info(
                            f"Deleted {len(part) - len(new_part)} ring(s) out of {len(part)} "
                            f"from part {i_part + 1} out of {len(multi_polygon)}"
                        )

            if len(new_multi_polygon) < len(multi_polygon):
                modified = True

            if modified:
                new_geometry = QgsGeometry.fromMultiPolygonXY(new_multi_polygon)

        # For single polygons
        elif geometry.type() == QgsWkbTypes.PolygonGeometry:
            polygon = geometry.asPolygon()
            rings_to_keep, polygon_modified = process_polygon(polygon)

            if polygon_modified:
                new_geometry = QgsGeometry.fromPolygonXY(rings_to_keep)
                _info("Deleted a ring from the polygon")
                modified = True

        if modified:
            self.layer.changeGeometry(feature.id(), new_geometry)
            return True

        return False

    def _finish_reshape(self):
        if not self.streaming or len(self.points) < 2:
            _warn("Draw a reshape line with at least 2 points.")
            return

        self.layer.beginEditCommand("Stream Edit")

        def _apply_changes():
            # Feature modified, clean up and return
            self.layer.endEditCommand()
            self.points = []
            self.streaming = False
            self.rubber_band.reset(QgsWkbTypes.LineGeometry)
            self.preview_band.reset(QgsWkbTypes.PolygonGeometry)
            self.intersection_band.reset(QgsWkbTypes.PointGeometry)
            self.canvas.refresh()

        if not self.drawing_mode:
            # close the loop
            closed_points = self.points + [self.points[0]]
            polygon_geom = QgsGeometry.fromPolygonXY([closed_points])

            # attempt to delete contained rings/parts in reshape mode
            if self._delete_circumvented_feature(polygon_geom):
                _apply_changes()
                return

            # Check if we need to add a new part (only in reshape mode)
            selected = self.layer.selectedFeatures()
            if len(selected) == 1:
                feature = selected[0]
                feature_geom = feature.geometry()

                # Check if the drawn polygon intersects the current feature
                intersects = feature_geom.intersects(polygon_geom)

                # Check if the drawn polygon circumvents any part of the feature
                circumvents = False
                if QgsWkbTypes.isMultiType(feature_geom.wkbType()):
                    multi_polygon = feature_geom.asMultiPolygon()
                    for part in multi_polygon:
                        for ring in part:
                            ring_geom = QgsGeometry.fromPolygonXY([ring])
                            if polygon_geom.contains(ring_geom):
                                circumvents = True
                                break
                        if circumvents:
                            break
                else:
                    polygon = feature_geom.asPolygon()
                    for ring in polygon:
                        ring_geom = QgsGeometry.fromPolygonXY([ring])
                        if polygon_geom.contains(ring_geom):
                            circumvents = True
                            break

                # If neither intersects nor circumvents, add as new part
                if not intersects and not circumvents:
                    if not QgsWkbTypes.isMultiType(feature_geom.wkbType()):
                        # Single polygon - convert to multi-polygon
                        multipolygon = []
                        multipolygon.append(feature_geom.asPolygon())  # Add existing polygon as first part
                        multipolygon.append([closed_points])  # Add new polygon as second part
                        new_geom = QgsGeometry.fromMultiPolygonXY(multipolygon)
                        self.layer.changeGeometry(feature.id(), new_geom)
                        _info("Added new part to feature (converted to multi-polygon)")
                    else:
                        # Already a multi-polygon
                        multipolygon = feature_geom.asMultiPolygon()
                        multipolygon.append([closed_points])
                        new_geom = QgsGeometry.fromMultiPolygonXY(multipolygon)
                        self.layer.changeGeometry(feature.id(), new_geom)
                        _info("Added new part to multi-polygon feature")

                    # Feature modified, clean up and return
                    _apply_changes()
                    return

                # If the drawn polygon is completely inside the feature (not intersecting border),
                # add it as a hole instead of trying to reshape
                if intersects and not circumvents and feature_geom.contains(polygon_geom):
                    if not QgsWkbTypes.isMultiType(feature_geom.wkbType()):
                        # Single polygon - add hole
                        polygon = feature_geom.asPolygon()
                        polygon.append(closed_points)  # Add new ring to existing polygon
                        new_geom = QgsGeometry.fromPolygonXY(polygon)
                        self.layer.changeGeometry(feature.id(), new_geom)
                        _info("Added new hole to polygon")
                    else:
                        # Multi-polygon - need to determine which part contains the new hole
                        multi_polygon = feature_geom.asMultiPolygon()
                        for i, part in enumerate(multi_polygon):
                            part_geom = QgsGeometry.fromPolygonXY(part)
                            if part_geom.contains(polygon_geom):
                                multi_polygon[i].append(closed_points)  # Add hole to this part
                                new_geom = QgsGeometry.fromMultiPolygonXY(multi_polygon)
                                self.layer.changeGeometry(feature.id(), new_geom)
                                _info(f"Added new hole to part {i + 1} of multi-polygon")
                                break

                    # Feature modified, clean up and return
                    _apply_changes()
                    return

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

            # Create a copy of the geometry to test the reshape operation
            test_geom = QgsGeometry(feature_geom)
            status = test_geom.reshapeGeometry(reshape_line.constGet())

            if status != QgsGeometry.OperationResult.Success:
                _warn("Reshape failed. Ensure the line crosses the polygon boundary.")
                self.layer.destroyEditCommand()
                return

            # Check if the resulting geometry would be valid
            if not test_geom.isGeosValid():
                _info("Reshape would create an invalid geometry. Attempting to merge overlapping parts...")

                # Create a buffer of 0 to clean the geometry and merge overlapping parts
                merged_geom = test_geom.buffer(0, 5)  # 5 segments for buffer approximation

                if merged_geom.isGeosValid():
                    self.layer.changeGeometry(selected_fid, merged_geom)
                    _info("Successfully merged overlapping parts to create a valid geometry.")
                else:
                    # Try alternative approach with makeValid
                    fixed_geom = test_geom.makeValid()
                    if fixed_geom.isGeosValid():
                        self.layer.changeGeometry(selected_fid, fixed_geom)
                        _info("Successfully repaired geometry with makeValid().")
                    else:
                        _warn("Failed to create valid geometry after reshape attempt.")
                        self.layer.destroyEditCommand()
                        return
            else:
                # Normal case - reshape produced a valid geometry
                self.layer.changeGeometry(selected_fid, test_geom)
                _info("Polygon successfully reshaped.")

        _apply_changes()

    def _repair_selected_geometry(self):
        selected = self.layer.selectedFeatures()
        if len(selected) != 1:
            _warn("Please select exactly one feature to repair.")
            return

        self.layer.beginEditCommand("Repair Geometry")
        feature = selected[0]
        geom = feature.geometry()

        if geom.isGeosValid():
            _info("Geometry is already valid.")
            self.layer.destroyEditCommand()
            return

        # Try buffer(0) approach first
        fixed_geom = geom.buffer(0, 5)
        if not fixed_geom.isGeosValid():
            # Try makeValid as backup
            fixed_geom = geom.makeValid()

        if fixed_geom.isGeosValid():
            self.layer.changeGeometry(feature.id(), fixed_geom)
            self.layer.endEditCommand()
            _info("Geometry repaired successfully.")
        else:
            self.layer.destroyEditCommand()
            _warn("Unable to repair geometry.")

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

        # From the special group, disable the items corresponding to the other glaciers
        root = QgsProject.instance().layerTreeRoot()
        target_group = root.findGroup('qgis_stream_tool')
        if target_group is None:
            return

        selected_feature = self.layer.selectedFeatures()
        if not selected_feature:
            return

        feature = selected_feature[0]
        entry_id = feature['entry_id']
        _info(f"Entry ID: {entry_id}")
        for child in target_group.children():
            if isinstance(child, QgsLayerTreeGroup) and 's2_' in child.name():
                for crt_layer in child.children():
                    crt_layer.setItemVisibilityChecked(entry_id in crt_layer.name())

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
