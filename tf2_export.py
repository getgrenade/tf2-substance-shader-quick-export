import os
import shutil
import tempfile
import substance_painter.export as sp_export
import substance_painter.project as sp_project
import substance_painter.ui as sp_ui
import substance_painter.textureset as sp_textureset
import substance_painter.resource as sp_resource
import substance_painter.layerstack as sp_layerstack
import substance_painter.logging as sp_logging
from PySide6 import QtWidgets, QtCore, QtGui

# Keep references so buttons aren't garbage collected
_toolbar        = None
_btn_export     = None
_btn_blue       = None
_btn_pick       = None
_btn_toggle     = None
_action_export  = None
_action_blue    = None
_action_pick    = None
_action_toggle  = None
_action_diagnose = None

# Session state
_selected_texture_sets = None   # None = all
_custom_export_path    = None   # None = use automatic path
_showing_blue          = False  # Toggle state: False = red visible, True = blue visible

# ── Diagnostics ───────────────────────────────────────────────────────────────

def diagnose_layer_colors():
    """Print all layer/folder properties to the Substance log."""
    all_ts = (sp_textureset.all_texture_sets() if sp_project.is_open() else [])
    if not all_ts:
        sp_logging.log(sp_logging.WARNING, "TF2Export", "No texture sets found.")
        return

    for ts in all_ts:
        sp_logging.log(sp_logging.INFO, "TF2Export", f"=== Texture Set: {ts.name} ===")
        try:
            stack = ts.get_stack()
            nodes = sp_layerstack.get_root_layer_nodes(stack)
            for node in nodes:
                attrs = [a for a in dir(node) if not a.startswith("_")]
                name  = node.get_name() if hasattr(node, "get_name") else "?"
                color = node.color_tag() if hasattr(node, "color_tag") else "N/A"
                sp_logging.log(sp_logging.INFO, "TF2Export",
                    f"  name='{name}' color_tag={color} attrs={attrs}")
        except Exception as e:
            sp_logging.log(sp_logging.ERROR, "TF2Export", f"Error: {e}")



PRESET_NAME = "TF2_Paint"
FILE_FORMAT = "tga"
BIT_DEPTH   = 8
DITHERING   = False
PADDING     = "infinite"

MAP_RESOLUTIONS = {
    "_diffuse" : 512,
    "_normal"  : 512,
    "_expmask" : 256,
}

BLUE_RESOLUTION = 512

# ── Icons (inline SVG) ────────────────────────────────────────────────────────

SVG_EXPORT = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20">
  <rect x="3" y="17" width="18" height="3" rx="1" fill="#cccccc"/>
  <polygon points="12,3 7,10 10,10 10,16 14,16 14,10 17,10" fill="#cccccc"/>
</svg>"""

SVG_EXPORT_BLUE = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20">
  <rect x="3" y="17" width="18" height="3" rx="1" fill="#4a90d9"/>
  <polygon points="12,3 7,10 10,10 10,16 14,16 14,10 17,10" fill="#4a90d9"/>
</svg>"""

SVG_PICK = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20">
  <rect x="3" y="4" width="4" height="4" rx="1" fill="#cccccc"/>
  <rect x="9" y="5" width="12" height="2" rx="1" fill="#cccccc"/>
  <rect x="3" y="10" width="4" height="4" rx="1" fill="#cccccc"/>
  <rect x="9" y="11" width="12" height="2" rx="1" fill="#cccccc"/>
  <rect x="3" y="16" width="4" height="4" rx="1" fill="#cccccc"/>
  <rect x="9" y="17" width="12" height="2" rx="1" fill="#cccccc"/>
  <polyline points="4,6 5,7 7,4" fill="none" stroke="#4a90d9" stroke-width="1.5"/>
</svg>"""


SVG_TOGGLE_BLUE = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20">
  <rect x="2" y="5" width="9" height="14" rx="2" fill="#cc4444"/>
  <rect x="13" y="5" width="9" height="14" rx="2" fill="#4a90d9"/>
  <rect x="10" y="8" width="4" height="8" rx="1" fill="#cccccc"/>
</svg>"""


def svg_to_icon(svg_bytes):
    pixmap = QtGui.QPixmap()
    pixmap.loadFromData(svg_bytes, "SVG")
    return QtGui.QIcon(pixmap)


# ── Path resolution ───────────────────────────────────────────────────────────

def try_auto_path():
    """
    Returns (path, ok) where ok=True if the project is in a /bakes/ folder.
    Always returns a path — but ok=False signals the user should set a custom one.
    """
    sp_file = sp_project.file_path() if sp_project.is_open() else None
    if not sp_file:
        raise RuntimeError("No project is open.")
    bakes_dir   = os.path.dirname(sp_file)
    project_dir = os.path.dirname(bakes_dir)
    in_bakes    = os.path.basename(bakes_dir).lower() == "bakes"
    output_dir  = os.path.join(project_dir, "texture")
    return output_dir, in_bakes


def get_texture_output_path(prompt_if_needed=True):
    """
    Returns the resolved export path.
    Priority: custom path → auto path (if in /bakes/) → prompt user to set one.
    """
    global _custom_export_path

    if _custom_export_path:
        os.makedirs(_custom_export_path, exist_ok=True)
        return _custom_export_path

    auto_path, in_bakes = try_auto_path()

    if in_bakes:
        os.makedirs(auto_path, exist_ok=True)
        return auto_path

    # Not in /bakes/ and no custom path set — prompt settings
    if prompt_if_needed:
        QtWidgets.QMessageBox.warning(
            None, "TF2 Export",
            "Project is not inside a /bakes/ folder.\n"
            "Please set a custom export path in settings."
        )
        open_settings()
        if _custom_export_path:
            return _custom_export_path

    raise RuntimeError(
        "Could not determine export path.\n"
        "Please set a custom export path in settings."
    )


# ── Active texture sets ───────────────────────────────────────────────────────

def get_active_texture_sets():
    global _selected_texture_sets
    all_ts = (sp_textureset.all_texture_sets() if sp_project.is_open() else [])
    if not _selected_texture_sets:
        return all_ts
    return [ts for ts in all_ts if ts.name in _selected_texture_sets]


# ── Settings dialog ───────────────────────────────────────────────────────────

def open_settings():
    global _selected_texture_sets, _custom_export_path

    all_ts = (sp_textureset.all_texture_sets() if sp_project.is_open() else [])

    dialog = QtWidgets.QDialog(sp_ui.get_main_window())
    dialog.setWindowTitle("TF2 Export Settings")
    dialog.setMinimumWidth(380)

    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setSpacing(12)

    # ── Export path ──
    layout.addWidget(QtWidgets.QLabel("<b>Export path</b>"))

    # Show what the auto path would be
    try:
        auto_path, in_bakes = try_auto_path()
        auto_label_text = f"Auto: {auto_path}" if in_bakes else f"Auto unavailable (not in /bakes/)"
    except Exception:
        auto_label_text = "Auto: no project open"

    auto_label = QtWidgets.QLabel(auto_label_text)
    auto_label.setStyleSheet("color: gray; font-size: 11px;")
    layout.addWidget(auto_label)

    path_row = QtWidgets.QHBoxLayout()
    path_edit = QtWidgets.QLineEdit()
    path_edit.setPlaceholderText("Leave empty to use automatic path")
    if _custom_export_path:
        path_edit.setText(_custom_export_path)

    browse_btn = QtWidgets.QPushButton("Browse…")
    clear_btn  = QtWidgets.QPushButton("Clear")

    def browse():
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            dialog, "Select export folder", path_edit.text() or ""
        )
        if folder:
            path_edit.setText(folder)

    def clear():
        path_edit.clear()

    browse_btn.clicked.connect(browse)
    clear_btn.clicked.connect(clear)

    path_row.addWidget(path_edit)
    path_row.addWidget(browse_btn)
    path_row.addWidget(clear_btn)
    layout.addLayout(path_row)

    # ── Texture sets ──
    layout.addWidget(QtWidgets.QLabel("<b>Texture sets to export</b>"))

    checkboxes = []
    if all_ts:
        for ts in all_ts:
            cb = QtWidgets.QCheckBox(ts.name)
            if _selected_texture_sets is None or ts.name in _selected_texture_sets:
                cb.setChecked(True)
            checkboxes.append(cb)
            layout.addWidget(cb)

        btn_row = QtWidgets.QHBoxLayout()
        btn_all  = QtWidgets.QPushButton("All")
        btn_none = QtWidgets.QPushButton("None")
        btn_all.clicked.connect(lambda: [cb.setChecked(True)  for cb in checkboxes])
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in checkboxes])
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)
    else:
        layout.addWidget(QtWidgets.QLabel("(No texture sets — open a project first)"))

    # ── OK / Cancel ──
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() == QtWidgets.QDialog.Accepted:
        # Save custom path
        text = path_edit.text().strip()
        _custom_export_path = text if text else None

        # Save texture set selection
        if checkboxes:
            selected = [cb.text() for cb in checkboxes if cb.isChecked()]
            _selected_texture_sets = selected if selected else None


# ── Export ────────────────────────────────────────────────────────────────────

def run_export(output_dir, maps):
    texture_sets = get_active_texture_sets()
    if not texture_sets:
        raise RuntimeError("No texture sets selected.")

    try:
        rid = sp_resource.ResourceID(context="starter_assets", name=PRESET_NAME)
        preset_url = rid.url()
    except Exception as e:
        raise RuntimeError(f"Could not find preset '{PRESET_NAME}' in starter_assets.\nDetail: {e}")

    SIZE_LOG2 = {256: 8, 512: 9, 1024: 10, 2048: 11, 4096: 12}

    resolution_groups = {}
    for suffix, res in maps:
        resolution_groups.setdefault(res, []).append(suffix)

    for res, suffixes in resolution_groups.items():
        config = {
            "exportShaderParams" : False,
            "exportPath"         : output_dir,
            "defaultExportPreset": preset_url,
            "exportList"         : [
                {
                    "rootPath"    : ts.name,
                    "exportPreset": preset_url,
                    "filter"      : {
                        "outputMaps": [f"$textureSet{s}" for s in suffixes]
                    }
                }
                for ts in texture_sets
            ],
            "exportParameters": [{
                "parameters": {
                    "fileFormat"      : FILE_FORMAT,
                    "bitDepth"        : str(BIT_DEPTH),
                    "dithering"       : DITHERING,
                    "paddingAlgorithm": PADDING,
                    "sizeLog2"        : SIZE_LOG2.get(res, 9),
                }
            }],
        }
        sp_export.export_project_textures(config)


def export_full():
    try:
        output_dir = get_texture_output_path()
        run_export(output_dir, list(MAP_RESOLUTIONS.items()))
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "Export failed", str(e))


def export_blue():
    try:
        output_dir   = get_texture_output_path()
        texture_sets = get_active_texture_sets()
        if not texture_sets:
            raise RuntimeError("No texture sets selected.")

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_export(tmp_dir, [("_diffuse", BLUE_RESOLUTION)])
            for ts in texture_sets:
                src = os.path.join(tmp_dir, f"{ts.name}_diffuse.{FILE_FORMAT}")
                dst = os.path.join(output_dir, f"{ts.name}_diffuse_blue.{FILE_FORMAT}")
                if os.path.isfile(src):
                    shutil.copy2(src, dst)

    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "Export Blue failed", str(e))


def toggle_red_blue():
    """Toggle visibility of _red and _blue named layers across all texture sets."""
    global _showing_blue, _btn_toggle

    all_ts = (sp_textureset.all_texture_sets() if sp_project.is_open() else [])
    if not all_ts:
        return

    # Flip state
    _showing_blue = not _showing_blue

    def set_layer_visibility(node, show_blue):
        name = node.get_name().lower()
        if "_red" in name:
            node.set_visible(not show_blue)
        elif "_blue" in name:
            node.set_visible(show_blue)
        # Recurse into group children
        if hasattr(node, "sub_layers"):
            for child in node.sub_layers():
                set_layer_visibility(child, show_blue)

    for ts in all_ts:
        try:
            stack = ts.get_stack()
            for node in sp_layerstack.get_root_layer_nodes(stack):
                set_layer_visibility(node, _showing_blue)
        except Exception as e:
            sp_logging.log(sp_logging.ERROR, "TF2Export", f"Toggle error: {e}")

    # Update button tooltip to reflect current state
    if _btn_toggle:
        state = "blue" if _showing_blue else "red"
        _btn_toggle.setToolTip(f"Toggle red/blue layers — currently showing {state}")


# ── Toolbar ───────────────────────────────────────────────────────────────────

def start_plugin():
    global _toolbar, _btn_export, _btn_blue, _btn_pick, _btn_toggle
    global _action_export, _action_blue, _action_pick, _action_toggle
    global _action_diagnose

    main_window = sp_ui.get_main_window()

    _toolbar = next(
        (t for t in main_window.findChildren(QtWidgets.QToolBar)
         if t.objectName() == "widgets_quick_buttons"),
        None
    )

    if _toolbar is None:
        QtWidgets.QMessageBox.critical(None, "TF2 Export", "Could not find toolbar.")
        return

    _btn_pick = QtWidgets.QToolButton()
    _btn_pick.setIcon(svg_to_icon(SVG_PICK))
    _btn_pick.setIconSize(QtCore.QSize(20, 20))
    _btn_pick.setToolTip("TF2 Export Settings")
    _btn_pick.setFixedSize(24, 24)
    _btn_pick.clicked.connect(open_settings)

    _btn_export = QtWidgets.QToolButton()
    _btn_export.setIcon(svg_to_icon(SVG_EXPORT))
    _btn_export.setIconSize(QtCore.QSize(20, 20))
    _btn_export.setToolTip("TF2 Export — diffuse/normal (512), expmask (256)")
    _btn_export.setFixedSize(24, 24)
    _btn_export.clicked.connect(export_full)

    _btn_blue = QtWidgets.QToolButton()
    _btn_blue.setIcon(svg_to_icon(SVG_EXPORT_BLUE))
    _btn_blue.setIconSize(QtCore.QSize(20, 20))
    _btn_blue.setToolTip("TF2 Export Blue — diffuse_blue (512)")
    _btn_blue.setFixedSize(24, 24)
    _btn_blue.clicked.connect(export_blue)

    _btn_toggle = QtWidgets.QToolButton()
    _btn_toggle.setIcon(svg_to_icon(SVG_TOGGLE_BLUE))
    _btn_toggle.setIconSize(QtCore.QSize(20, 20))
    _btn_toggle.setToolTip("Toggle red/blue layers — currently showing red")
    _btn_toggle.setFixedSize(24, 24)
    _btn_toggle.clicked.connect(toggle_red_blue)

    _toolbar.addSeparator()
    _action_pick   = _toolbar.addWidget(_btn_pick)
    _action_toggle = _toolbar.addWidget(_btn_toggle)
    _action_export = _toolbar.addWidget(_btn_export)
    _action_blue   = _toolbar.addWidget(_btn_blue)

    _action_diagnose = QtGui.QAction("TF2 Export: Diagnose Layer Colors", main_window)
    _action_diagnose.triggered.connect(diagnose_layer_colors)
    sp_ui.add_action(sp_ui.ApplicationMenu.File, _action_diagnose)


def close_plugin():
    global _toolbar, _action_export, _action_blue, _action_pick, _action_toggle
    global _btn_export, _btn_blue, _btn_pick, _btn_toggle
    global _action_diagnose
    if _action_diagnose is not None:
        sp_ui.delete_ui_element(_action_diagnose)
        _action_diagnose = None
    if _toolbar:
        for action in (_action_pick, _action_toggle, _action_export, _action_blue):
            if action:
                _toolbar.removeAction(action)
    _toolbar        = None
    _btn_export     = None
    _btn_blue       = None
    _btn_pick       = None
    _btn_toggle     = None
    _action_export  = None
    _action_blue    = None
    _action_pick    = None
    _action_toggle  = None


if __name__ == "__main__":
    start_plugin()
