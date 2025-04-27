# QGISStreamTool
🛠️ QGISStreamTool: Keyboard-Driven Polygon Drawing & Reshaping for QGIS


QGISStreamTool is a custom QGIS digitizing tool that enables fast, keyboard-controlled editing of polygon features. It supports both streaming contour creation and interactive reshaping, with smart background toggling and feature navigation.

QGIS provides digitizing tools out of the box (incl. "Add Polygon Feature", "Reshape Features", "Digitize with Segment", "Stream Digitizing"). 
However, I was missing some features that helped me for correcting shapefiles produced by automatic methods.

✨ QGISStreamTool Features
- 🧲 Stream digitizing (press R):
  - same as the original "Stream Digitizing" tool but with tolerance expressed in meters
- 🔁 Reshape mode: update existing polygons using a drawn line
  - same as the original "Reshape Features" tool but allows placing vertices by pressing the Space key
- 🗂️ Group visibility control: show/hide background layer groups with number keys
- 🔍 Feature navigation: jump to next/previous polygon by pressing Ctrl+] / Ctrl+[

🤖 Note: Most of the code for this tool was generated collaboratively using Copilot, including this description :)

