# QGISStreamTool

🛠️ QGISStreamTool: Keyboard-Driven Polygon Drawing & Reshaping for QGIS

QGIS provides digitizing tools out of the box (incl. "Add Polygon Feature", "Reshape Features", "Digitize with
Segment", "Stream Digitizing"). However, I was missing some features that make it easy to edit (multi)polygons produced
by automatic methods, all accessible in a single tool with keyboard shortcuts.

## ✨ Features

### 🎮 Shortcuts

- **Y**: Toggle between _Drawing mode_ (create new features) and _Reshape mode_ (edit existing features)
- **R**: Toggle _streaming mode_ on/off (automatic vertex placement while moving). This is similar to the original "
  Stream Digitizing" tool but with tolerance expressed in map units (meters). This is currently hardcoded to 3 meters,
  but you can change it in the code.
- **Space**: Manually add vertex at cursor position (useful when streaming is off; to me, it feels easier to place
  vertices manually by pressing Space instead of clicking in order to avoid deviating from the intended shape)
- **Enter** or **Right-click**: Complete the current drawing/reshape operation
- **S**: Save edits (commit changes)
- **ESC**: Cancel current operation/exit tool
- **[**: Navigate (and zoom) to previous feature
- **]**: Navigate (and zoom) to next feature

### 🔄 Smart Reshape Operations

- Automatic detection of boundary intersections (shows green dots where the reshape line crosses polygon boundaries)
- Add holes when drawing inside polygons
- Add new parts to multi-polygons when drawing isolated areas
- Delete all contained rings/parts when circumvented by reshape line

### 🌐 Background Control

This feature is particularly useful when you need to quickly compare different background references while digitizing
features.
To be able to use it, you need to set up a specific layer structure in QGIS:

1. **Create a main group layer named** `qgis_stream_tool`
2. **Create subgroups with specific naming pattern**:
    - Inside the main group, create subgroups with names that **start with** `g_` followed by a digit (0-9).
    - Example subgroup names:
        - `g_0_satellite`
        - `g_1_hillshade`
        - `g_2_inventory_xyz`
        - `g_3_dhdt`
        - ...

3. **Organize your layers:**
    - Place relevant background layers within these subgroups (they can be anything, e.g. rasters, vectors, etc.)

#### Example Structure

```
qgis_stream_tool/
├── g_0_satellite_imagery/
│   ├── high_resolution.tif
│   └── low_resolution.tif
├── g_1_hillshade/
│   └── dem_hillshade.tif
├── g_2_contours/
│   ├── major_contours.shp
│   └── minor_contours.shp
├── g_3_historical/
│   ├── imagery_1950.tif
│   └── imagery_1970.tif
```

#### Usage

- Press keys `0`-`9` to toggle visibility between different background layer sets. When you press a number key, we make
  only the corresponding `g_X` subgroup visible (and **all other** subgroups in the `qgis_stream_tool` group are
  hidden).

## 🤖 Note:

- The code was tested only for 3.42.1 on Ubuntu 24.04.1 LTS.
- The tool is not (yet) a plugin, but you can copy the code into a Python file and run it in the QGIS Python console.
  Check the log messages for inputs.
- I assume that:
  - the polygon layer to be edited is the active layer
  - editing is enabled 
  - the current feature to be reshaped is selected
  - the layer has no Z dimension
  - both the layer and the project are in the **same** **projected** CRS
- Most of the code for this tool was generated collaboratively using Copilot, including a major part of this
  description :)

Feel free to open an issue if you find a bug or have a feature request.
