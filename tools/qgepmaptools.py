# -*- coding: utf-8 -*-
# -----------------------------------------------------------
#
# Qgep
# Copyright (C) 2012  Matthias Kuhn
# -----------------------------------------------------------
#
# licensed under the terms of GNU GPL 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, print to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# ---------------------------------------------------------------------

"""
This module implements several map tools for QGEP
"""

from qgis.core import (
    QgsGeometry,
    QgsPoint,
    QGis,
    QgsFeatureRequest,
    QgsSnappingUtils,
    QgsTolerance,
    QgsPointLocator,
    QgsFeature
)
from qgis.gui import (
    QgsMapTool,
    QgsRubberBand,
    QgsVertexMarker,
    QgsMessageBar,
    QgsMapCanvasSnappingUtils
)
from PyQt4.QtGui import (
    QCursor,
    QColor,
    QApplication,
    QDialog,
    QFormLayout,
    QCheckBox,
    QDialogButtonBox
)
from PyQt4.QtCore import (
    Qt,
    QPoint,
    pyqtSignal,
    QSettings,
    QCoreApplication
)
from .qgepprofile import (
    QgepProfile,
    QgepProfileNodeElement,
    QgepProfileReachElement,
    QgepProfileSpecialStructureElement
)
from qgepplugin.utils.qgeplayermanager import QgepLayerManager

import logging


class QgepMapTool(QgsMapTool):
    """
    Base class for all the map tools
    """

    highLightedPoints = []
    logger = logging.getLogger(__name__)

    def __init__(self, iface, button):
        QgsMapTool.__init__(self, iface.mapCanvas())
        self.canvas = iface.mapCanvas()
        self.cursor = QCursor(Qt.CrossCursor)
        self.button = button
        self.msgBar = iface.messageBar()

        settings = QSettings()
        current_profile_color = settings.value(
            "/QGEP/CurrentProfileColor", u'#FF9500')

        self.rubberBand = QgsRubberBand(self.canvas)
        self.rubberBand.setColor(QColor(current_profile_color))
        self.rubberBand.setWidth(3)

    def activate(self):
        """
        Gets called when the tool is activated
        """
        QgsMapTool.activate(self)
        self.canvas.setCursor(self.cursor)
        self.button.setChecked(True)

    def deactivate(self):
        """
        Gets called whenever the tool is deactivated directly or indirectly
        """
        QgsMapTool.deactivate(self)
        self.button.setChecked(False)

    # pylint: disable=no-self-use
    def isZoomTool(self):
        """
        Will return if this is a zoom tool
        """
        return False

    def setCursor(self, cursor):
        """
        Set the cursor for this maptool
        """
        self.cursor = QCursor(cursor)

    # ===========================================================================
    # Events
    # ===========================================================================

    def canvasReleaseEvent(self, event):
        """
        Issues rightClicked and leftClicked events
        """
        if event.button() == Qt.RightButton:
            self.rightClicked(event)
        else:
            self.leftClicked(event)

    def canvasDoubleClickEvent(self, event):
        """
        Forwards to doubleClicked
        """
        try:
            self.doubleClicked(event)
        except AttributeError:
            pass


class QgepProfileMapTool(QgepMapTool):
    """
    The map tool used for PROFILE

    Allows to find the shortest path between several nodes.
    """
    profileChanged = pyqtSignal(object)
    profile = QgepProfile()
    segmentOffset = 0

    selectedPathPoints = []
    pathPolyline = []

    def __init__(self, canvas, button, network_analyzer):
        QgepMapTool.__init__(self, canvas, button)
        settings = QSettings()

        helper_line_color = settings.value("/QGEP/HelperLineColor", u'#FFD900')
        highlight_color = settings.value("/QGEP/HighlightColor", u'#40FF40')

        self.networkAnalyzer = network_analyzer

        # Init rubberband to visualize current status
        self.rbHelperLine = QgsRubberBand(self.canvas)
        self.rbHelperLine.setColor(QColor(helper_line_color))
        self.rbHelperLine.setWidth(2)

        self.rbHighlight = QgsRubberBand(self.canvas)
        self.rbHighlight.setColor(QColor(highlight_color))
        self.rbHighlight.setWidth(5)

        self.profile.setRubberband(self.rbHighlight)

        self.saveTool = None

    def setActive(self):
        """
        activates this map tool
        """
        self.saveTool = self.canvas.mapTool()
        self.canvas.setMapTool(self)

    def deactivate(self):
        """
        Called whenever this map tool is deactivated.
        Used to clean up code
        """
        QgepMapTool.deactivate(self)
        self.rubberBand.reset()
        self.rbHelperLine.reset()
        self.selectedPathPoints = []
        self.pathPolyline = []

    def findPath(self, start_point, end_point):
        """
        Tries to find the shortest path between pStart and pEnd.
        If it finds a path:
         * The path is visualized with a QgsRubberband
         * The profile plot is updated to represent the current path

        @param start_point: The id of the start point of the path
        @param end_point:   The id of the end point of the path
        """
        QApplication.setOverrideCursor(Qt.WaitCursor)
        # try:
        (vertices, edges) = self.networkAnalyzer.shortestPath(
            start_point, end_point)
        self.appendProfile(vertices, edges)
        #        except:
        #            pass
        QApplication.restoreOverrideCursor()
        if len(vertices) > 0:
            return True
        else:
            return False

    # pylint: disable=too-many-locals
    def appendProfile(self, vertices, edges):
        """
        Appends to the current profile

        @param vertices: A collection of vertices to append
        @param edges:    A collection of edges which connect the vertices
        """
        self.logger.debug('Append profile')
        self.logger.info(' * ' + repr(len(vertices)) + ' vertices')
        for v in vertices:
            self.logger.debug('   *' + repr(v))
        self.logger.info(' * ' + repr(len(edges)) + ' edges')
        for e in edges:
            self.logger.debug('   *' + repr(e))

        # Fetch all the needed edges in one batch
        edge_layer = self.networkAnalyzer.getReachLayer()
        edge_ids = [edge['feature'] for p1, p2, edge in edges]

        edge_features = self.networkAnalyzer.getFeaturesById(
            edge_layer, edge_ids)

        # We need some additional nodes, where we need to interpolate...
        interpolate_nodes_from = [edge_features.attrAsUnicode(feat, u'from_obj_id_interpolate')
                                  for feat in edge_features.asDict().values()]
        interpolate_nodes_to = [edge_features.attrAsUnicode(feat, u'to_obj_id_interpolate')
                                for feat in edge_features.asDict().values()]
        additional_ids = [self.networkAnalyzer.vertexIds[node]
                          for node in interpolate_nodes_from]
        additional_ids += [self.networkAnalyzer.vertexIds[node]
                           for node in interpolate_nodes_to]

        # Now, fetch the nodes we need
        node_layer = self.networkAnalyzer.getNodeLayer()
        node_ids = vertices + additional_ids
        node_features = self.networkAnalyzer.getFeaturesById(
            node_layer, node_ids)

        if len(vertices) > 1:
            self.rubberBand.reset()

            elem = QgepProfileNodeElement(vertices[0], node_features, 0)
            self.profile.addElement(vertices[0], elem)

            for p1, p2, edge in edges:
                from_offset = self.segmentOffset
                to_offset = self.segmentOffset + edge['weight']

                if 'reach' == edge['objType']:
                    if self.profile.hasElement(edge['baseFeature']):
                        self.profile[edge['baseFeature']] \
                            .addSegment(p1, p2, edge['feature'], node_features,
                                        edge_features, from_offset, to_offset)
                    else:
                        elem = QgepProfileReachElement(p1, p2, edge['feature'],
                                                       node_features, edge_features,
                                                       from_offset, to_offset)
                        self.profile.addElement(elem.obj_id, elem)

                elif 'special_structure' == edge['objType']:
                    if self.profile.hasElement(edge['baseFeature']):
                        self.profile[edge['baseFeature']] \
                            .addSegment(p1, p2, edge['feature'], node_features,
                                        edge_features, from_offset, to_offset)
                    else:
                        elem = QgepProfileSpecialStructureElement(p1, p2, edge['feature'],
                                                                  node_features, edge_features,
                                                                  from_offset, to_offset)
                        self.profile.addElement(elem.obj_id, elem)

                elem = QgepProfileNodeElement(p2, node_features, to_offset)
                self.profile.addElement(p2, elem)

                self.segmentOffset = to_offset

            self.profileChanged.emit(self.profile)

            # Create rubberband geometry
            for featId in edge_ids:
                self.pathPolyline.extend(
                    edge_features[featId].geometry().asPolyline())

            self.rubberBand.addGeometry(
                QgsGeometry.fromPolyline(self.pathPolyline), node_layer)
            self.profileChanged.emit(self.profile)
            return True
        else:
            return False

    def canvasMoveEvent(self, event):
        """
        Mouse moved: update helper line

        @param event: The mouse event with coordinates and all
        """
        if self.selectedPathPoints:
            self.rbHelperLine.reset()
            for point in self.selectedPathPoints:
                self.rbHelperLine.addPoint(point[1])
            mouse_pos = self.canvas.getCoordinateTransform() \
                .toMapCoordinates(event.pos().x(), event.pos().y())
            self.rbHelperLine.addPoint(mouse_pos)

    def rightClicked(self, _):
        """
        Cancel any ongoing path selection

        @param event: The mouse event with coordinates and all
        """
        self.selectedPathPoints = []
        self.pathPolyline = []
        self.rbHelperLine.reset()
        self.profile.reset()
        self.segmentOffset = 0

    def leftClicked(self, event):
        """
        Select startpoint / intermediate point / endpoint

        @param event: The mouse event with coordinates and all
        """
        snapped_point = self.networkAnalyzer.snapPoint(event)

        if snapped_point is not None:
            if self.selectedPathPoints:
                pf = self.findPath(
                    self.selectedPathPoints[-1][0], snapped_point.snappedAtGeometry)
                if pf:
                    self.selectedPathPoints.append(
                        (snapped_point.snappedAtGeometry, QgsPoint(snapped_point.snappedVertex)))
                else:
                    msg = self.msgBar.createMessage('No path found')
                    self.msgBar.pushWidget(msg, QgsMessageBar.WARNING)
            else:
                self.selectedPathPoints.append((snapped_point.snappedAtGeometry,
                                                QgsPoint(snapped_point.snappedVertex)))


class QgepTreeMapTool(QgepMapTool):
    """
    The map tool used to find TREES (upstream or downstream)
    """

    treeChanged = pyqtSignal(list, list)

    def __init__(self, canvas, button, network_analyzer):
        QgepMapTool.__init__(self, canvas, button)

        self.direction = "downstream"
        self.networkAnalyzer = network_analyzer
        self.saveTool = None

    def setDirection(self, direction):
        """
        Set the direction to track the graph.
        :param direction:  Can be 'upstream' or 'downstream'
        """
        self.direction = direction

    def getTree(self, point):
        """
        Does the work. Tracks the graph up- or downstream.
        :param point: The node from which the tracking should be started
        """
        QApplication.setOverrideCursor(Qt.WaitCursor)
        upstream = False
        if self.direction == "upstream":
            upstream = True

        self.rubberBand.reset()

        nodes, edges = self.networkAnalyzer.getTree(point, upstream)
        polylines = self.networkAnalyzer.getEdgeGeometry(
            [edge[2]['feature'] for edge in edges])

        # Fix for QGIS < 2.0
        filtered_polylines = [pl for pl in polylines if pl]

        self.rubberBand.addGeometry(QgsGeometry.fromMultiPolyline(filtered_polylines),
                                    self.networkAnalyzer.getNodeLayer())

        self.treeChanged.emit(nodes, edges)

        QApplication.restoreOverrideCursor()

    def canvasMoveEvent(self, event):
        """
        Whenever the mouse is moved update the rubberband and the snapping.
        :param event: QMouseEvent with coordinates
        """
        point_clicked = QPoint(event.pos().x(), event.pos().y())
        (_, snapped_points) = self.networkAnalyzer.getSnapper(
        ).snapPoint(point_clicked, [])

        for marker in self.highLightedPoints:
            self.canvas.scene().removeItem(marker)

        self.highLightedPoints = []

        if snapped_points:
            for point in snapped_points:
                marker = QgsVertexMarker(self.canvas)
                marker.setCenter(point.snappedVertex)
                marker.setColor(QColor("#FFFF33"))
                marker.setIconSize(10)
                marker.setIconType(QgsVertexMarker.ICON_X)
                marker.setPenWidth(2)
                self.highLightedPoints.append(marker)

    def rightClicked(self, _):
        """
        Resets the rubberband on right clickl
        :param _: QMouseEvent
        """
        self.rubberBand.reset()

    def leftClicked(self, event):
        """
        Snaps to the network graph
        :param event: QMouseEvent
        """
        snapped_point = self.networkAnalyzer.snapPoint(event)

        if snapped_point is not None:
            self.getTree(snapped_point.snappedAtGeometry)

    def setActive(self):
        """
        Activates this map tool
        """
        self.saveTool = self.canvas.mapTool()
        self.canvas.setMapTool(self)

    def deactivate(self):
        """
        Deactivates this map tool. Removes the rubberband etc.
        """
        QgepMapTool.deactivate(self)
        self.rubberBand.reset()

        for marker in self.highLightedPoints:
            self.canvas.scene().removeItem(marker)

        self.highLightedPoints = []


class QgepAreaSnapper(QgsMapCanvasSnappingUtils):

    def __init__(self, map_canvas):
        QgsMapCanvasSnappingUtils.__init__(self, map_canvas)

    def snapToMap(self, pt):
        match = QgsMapCanvasSnappingUtils.snapToMap(self, pt)

        if not match.isValid() and self.snapToMapMode() == QgsSnappingUtils.SnapAdvanced:
            for layer in self.layers():
                if layer.type & QgsPointLocator.Area:
                    loc = self.locatorForLayer(layer.layer)
                    results = loc.pointInPolygon(pt)
                    if results:
                        return results[0]

        return match


class QgepMapToolConnectNetworkElements(QgsMapTool):
    """
    This map tool connects wastewater networkelements.

    It works on two lists of layers:
      source layers with fields with a foreign key to a networkelement
      target layers which depict networkelements (reaches and network nodes)

    The tool will snap to source layers first and once one is chosen to a target layer.

    It will then ask which field(s) should be connected and perform the update on the database
    """

    def __init__(self, iface, action):
        QgsMapTool.__init__(self, iface.mapCanvas())
        self.iface = iface
        self.action = action

        self.rbline = QgsRubberBand(self.iface.mapCanvas(), QGis.Line)
        self.rbline.setColor(QColor('#f4530e'))
        self.rbline.setWidth(3)
        self.rbmarkers = QgsRubberBand(self.iface.mapCanvas(), QGis.Point)
        self.rbmarkers.setColor(QColor('#f4530e'))
        self.rbmarkers.setIconSize(6)

        self.source_snapper = QgepAreaSnapper(self.iface.mapCanvas())
        self.target_snapper = QgepAreaSnapper(self.iface.mapCanvas())

        self.source_feature = QgsFeature()
        self.rb_source_feature = QgsRubberBand(self.iface.mapCanvas())
        self.rb_source_feature.setColor(QColor('#f49e79'))
        self.rb_source_feature.setWidth(3)
        self.target_feature = QgsFeature()
        self.rb_target_feature = QgsRubberBand(self.iface.mapCanvas())
        self.rb_target_feature.setColor(QColor('#f49e79'))
        self.rb_target_feature.setWidth(3)

    def activate(self):
        """
        Called by QGIS whenever the tool is activated.
        """

        # A dict of layers
        #  and for each layer the fields to use as foreign key
        #  as well as the possible target layers
        # Reaches can be connected to reaches and nodes
        # Catchment areas only to nodes
        self.network_element_sources = {
            QgepLayerManager.layer('vw_qgep_reach'): {
                'fields': [
                    ('rp_to_fk_wastewater_networkelement',
                     QCoreApplication.translate('QgepMapToolConnectNetworkElements', 'Reach Point To')),
                    ('rp_from_fk_wastewater_networkelement',
                     QCoreApplication.translate('QgepMapToolConnectNetworkElements', 'Reach Point From'))
                ],
                'target_layers': [
                    QgepLayerManager.layer('vw_wastewater_node'),
                    QgepLayerManager.layer('vw_qgep_reach')
                ]},
            QgepLayerManager.layer('od_catchment_area'): {'fields': [
                ('fk_wastewater_networkelement_rw_current', QCoreApplication.translate(
                    'QgepMapToolConnectNetworkElements', 'Rainwater current')),
                ('fk_wastewater_networkelement_rw_planned', QCoreApplication.translate(
                    'QgepMapToolConnectNetworkElements', 'Rainwater planned')),
                ('fk_wastewater_networkelement_ww_current', QCoreApplication.translate(
                    'QgepMapToolConnectNetworkElements', 'Wastewater current')),
                ('fk_wastewater_networkelement_ww_planned', QCoreApplication.translate(
                    'QgepMapToolConnectNetworkElements', 'Wastewater planned'))
            ],
                'target_layers': [
                QgepLayerManager.layer('vw_wastewater_node')
            ]}
        }

        self.setSnapLayers(self.source_snapper,
                           self.network_element_sources.keys())

        self.reset()

        self.action.setChecked(True)

        self.iface.mapCanvas().setCursor(QCursor(Qt.CrossCursor))

    def setSnapLayers(self, snapper, layers):
        snap_layers = list()
        for layer in layers:
            if layer:
                snap_layer = QgsSnappingUtils.LayerConfig(
                    layer, QgsPointLocator.All, 16, QgsTolerance.Pixels)
                snap_layers.append(snap_layer)

        snapper.setLayers(snap_layers)
        snapper.setSnapToMapMode(QgsSnappingUtils.SnapAdvanced)

    def canvasMoveEvent(self, event):
        """
        When the mouse moves, update the rubberbands.
        """
        pt = event.originalMapPoint()
        snap_match = self.snapper.snapToMap(pt)

        if snap_match.isValid():
            if snap_match.type() != QgsPointLocator.Area:
                pt = snap_match.point()
            self.matchpoint = pt

            if self.source_match:
                # There is already a source feature : snap to target feature
                # candidates
                if self.target_feature.id() != snap_match.featureId():
                    self.target_feature = self.get_feature_for_match(
                        snap_match)
                    self.rb_target_feature.setToGeometry(
                        self.target_feature.geometry(), snap_match.layer())
                self.rb_target_feature.show()
                self.rbmarkers.movePoint(pt)
            else:
                # Snapped to source feature, update source feature rubber band
                # and target layer snapper
                if self.source_feature.id() != snap_match.featureId():
                    self.source_feature = self.get_feature_for_match(
                        snap_match)
                    self.rb_source_feature.setToGeometry(
                        self.source_feature.geometry(), snap_match.layer())
                    self.setSnapLayers(self.target_snapper, self.network_element_sources[
                                       snap_match.layer()]['target_layers'])
                self.rb_source_feature.show()
                self.rbmarkers.movePoint(pt, 0)
            self.rbmarkers.show()
        else:
            self.rbmarkers.hide()
            if self.source_match:
                self.rb_target_feature.hide()
            else:
                self.rb_source_feature.hide()

        self.rbline.movePoint(pt)

        self.snapresult = snap_match

    def canvasReleaseEvent(self, event):
        """
        On a click update the rubberbands and the snapping results if it's a left click. Reset if it's a right click.
        """
        if event.button() == Qt.LeftButton:
            if self.snapresult.isValid():
                if self.source_match:
                    self.connect_features(self.source_match, self.snapresult)
                else:
                    self.rbline.show()
                    self.rbline.addPoint(self.matchpoint)
                    self.source_match = self.snapresult
                    self.snapper = self.target_snapper
        else:
            self.reset()

    def deactivate(self):
        """
        Called by QGIS whenever this tool is deactivated.
        """
        self.reset()
        self.action.setChecked(False)

    def reset(self):
        """
        Resets the tool to a pristine state
        """
        self.source_match = None
        self.rbline.hide()
        self.rbline.reset()
        self.rbmarkers.hide()
        self.rbmarkers.reset(QGis.Point)
        self.rbmarkers.addPoint(QgsPoint())
        self.snapresult = None
        self.source_match = None
        self.snapper = self.source_snapper
        self.source_feature = QgsFeature()
        self.target_feature = QgsFeature()
        self.rb_source_feature.reset()
        self.rb_target_feature.reset()

    def get_feature_for_match(self, match):
        """
        Get the feature for a snapping result
        @param match: The QgsPointLocator.SnapMatch object
        @return: A feature
        """
        return next(match.layer().getFeatures(QgsFeatureRequest().setFilterFid(match.featureId())))

    def connect_features(self, source, target):
        """
        Connects the source feature with the target feature.

        @param source: A QgsPointLocator.Match object. Its foreign key will be updated.
                       A dialog will be opened which asks the user for which foreign key(s) he wants to update.
        @param target: A QgsPointLocator.Match object. This feature will be used as link target.
                       Its obj_id attribute will be used as primary key.
        """
        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle(self.tr('Select properties to connect'))
        dlg.setLayout(QFormLayout())

        properties = list()

        for prop in self.network_element_sources[source.layer()]['fields']:
            cbx = QCheckBox(prop[1])
            cbx.setObjectName(prop[0])
            properties.append(cbx)
            dlg.layout().addWidget(cbx)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dlg.layout().addWidget(btn_box)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)

        source_feature = self.get_feature_for_match(source)
        target_feature = self.get_feature_for_match(target)

        if dlg.exec_():
            for cbx in properties:
                if cbx.isChecked():
                    source_feature[cbx.objectName()] = target_feature['obj_id']
            if source.layer().updateFeature(source_feature):
                self.iface.messageBar().pushMessage('QGEP',
                                                    self.tr('Connected {} to {}').format(
                                                        source_feature[
                                                            'identifier'],
                                                        target_feature['identifier']),
                                                    QgsMessageBar.INFO, 5)
            else:
                self.iface.messageBar().pushMessage('QGEP',
                                                    self.tr(
                                                        'Error connecting features'),
                                                    QgsMessageBar.WARNING, 5)

        self.reset()
