import sys
import os
import re
import requests
import threading
import time
from shiboken6 import isValid
import io
import zipfile
import shutil
from concurrent.futures import ThreadPoolExecutor
import subprocess
import json
from win11toast import toast

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout,
    QWidget, QListWidget, QTreeWidgetItem, QListWidgetItem,
    QTreeWidget, QStackedWidget,
    QFrame, QProgressBar,QLineEdit, QScrollArea, QGridLayout,
    QDialog, QTextEdit, QFileDialog, QMessageBox, QSpinBox, QDialogButtonBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QObject
from PySide6.QtGui import QMouseEvent, QPixmap, QImage, QColor
 


CARD_W = 185
CARD_H = 280
IMG_H = 120
GRID_COLS = 3
CONFIG_FILE = "launcher_config.json"
GAMES_FILE = "games.json"
def load_games():

    try:

        with open(GAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        juegos = []
        repos = {}
        gamebanana_ids = {}

        for game in data["games"]:

            name = game["name"]

            juegos.append(name)

            repos[name] = game["repo"]

            gamebanana_ids[name] = game["gamebanana_id"]

        return juegos, repos, gamebanana_ids

    except Exception as e:

        print("Error cargando games.json:", e)

        return [], {}, {}
    
COLOR_BG = "#191919"
COLOR_PANEL = "#0a0a0a"
JUEGOS, REPOS, GAMEBANANA_IDS = load_games()
TABS = ["General", "Versiones", "Mods", "GameBanana"]

BASE_URL = "https://gamebanana.com/apiv11/Game/{}/Subfeed"



# -------------------------
# Releases Thread
# -------------------------
class ReleasesLoader(QThread):

    finished_loading = Signal(dict)

    def run(self):

        cache = {}

        for juego, repo in REPOS.items():

            try:

                r = requests.get(
                    f"https://api.github.com/repos/{repo}/releases?per_page=100",
                    timeout=15
                )

                cache[juego] = r.json()

            except:

                cache[juego] = []

        self.finished_loading.emit(cache)

# -------------------------
# Mods Download Threat
# -------------------------
class ModFileDownloadThread(QThread):

    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)

    def __init__(self, url, destination):
        super().__init__()

        self.url = url
        self.destination = destination

    def run(self):

        try:

            self.status.emit("Descargando...")

            r = requests.get(
                self.url,
                stream=True
            )

            total = int(
                r.headers.get(
                    "content-length",
                    0
                )
            )

            downloaded = 0

            with open(self.destination, "wb") as f:

                for chunk in r.iter_content(8192):

                    if not chunk:
                        continue

                    f.write(chunk)

                    downloaded += len(chunk)

                    if total:

                        percent = int(
                            downloaded * 100 / total
                        )

                        self.progress.emit(percent)

            # -------------------------
            # EXTRAER ZIP
            # -------------------------
            self.finished.emit(
                self.destination
            )

        except Exception as e:

            self.status.emit(
                f"Error: {e}"
            )

# -------------------------
# Mods Select Dialog
# -------------------------
class ZipSelectionDialog(QDialog):

    def __init__(self, zip_file, parent=None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint
        )

        self.setStyleSheet("""
            QDialog {
                background:#232323;
                border-radius:14px;
                border:1px solid #000000;
            }

            QLabel {
                color:white;
                font-size:12px;
                font-weight:bold;
            }

            QPushButton {
                background:#3a3a3a;
                color:white;
                border:none;
                border-radius:8px;
                padding:8px 14px;
                min-width:80px;
            }

            QPushButton:hover {
                background:#707070;
            }

            QTreeWidget {
                background:#1e1e1e;
                color:white;
                border:1px solid #000;
            }

            QScrollBar:vertical {
                background:#1e1e1e;
                width:10px;
                margin:0px;
            }

            QScrollBar::handle:vertical {
                background:#3a3a3a;
                border-radius:5px;
                min-height:20px;
            }

            QScrollBar::handle:vertical:hover {
                background:#C83C3C;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height:0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background:none;
            }
        """)

        self.resize(390,320)
        
        layout = QVBoxLayout(self)

        title = QLabel("Selecciona los archivos que deseas instalar")
        layout.addWidget(title)

        self.tree = QTreeWidget()

        self.tree.setHeaderHidden(True)

        layout.addWidget(self.tree)

        with zipfile.ZipFile(zip_file,"r") as z:

            for info in z.infolist():

                if info.is_dir():
                    continue

                item = QTreeWidgetItem([info.filename])

                item.setCheckState(
                    0,
                    Qt.Checked
                )

                self.tree.addTopLevelItem(item)

        buttons = QDialogButtonBox()

        install_btn = QPushButton("💾")

        buttons.addButton(
            install_btn,
            QDialogButtonBox.AcceptRole
        )

        install_btn.clicked.connect(self.accept)

        layout.addWidget(buttons)


    def selected_files(self):

        files=[]

        for i in range(self.tree.topLevelItemCount()):

            item=self.tree.topLevelItem(i)

            if item.checkState(0)==Qt.Checked:

                files.append(item.text(0))

        return files
    
# -------------------------
# 
# -------------------------        
class Bridge(QObject):
     mods_ready = Signal(int, list)
     image_ready = Signal(str, bytes, object)

# -------------------------
# 
# -------------------------
class FetchThread(threading.Thread):
    def __init__(self, gid, bridge):
        super().__init__(daemon=True)
        self.gid = gid
        self.bridge = bridge

    def run(self):
        mods = []
        page = 1

        while True:
            try:
                r = requests.get(
                    BASE_URL.format(self.gid),
                    params={"_nPage": page, "_nPerpage": 50},
                    timeout=10
                )
                data = r.json()
            except:
                break

            records = data.get("_aRecords", [])
            if not records:
                break

            for m in records:
                if m.get("_sModelName") not in ("Mod", "Wip"):
                    continue

                imgs = m.get("_aPreviewMedia", {}).get("_aImages", [])
                thumb = None

                if imgs:
                    b = imgs[0].get("_sBaseUrl")
                    f = imgs[0].get("_sFile")
                    if b and f:
                        thumb = f"{b}/{f}"

                mods.append({
                    "id": m.get("_idRow"),
                    "type": m.get("_sModelName"),
                    "name": m.get("_sName"),
                    "author": m.get("_aSubmitter", {}).get("_sName"),
                    "likes": m.get("_nLikeCount", 0),
                    "posts": m.get("_nPostCount", 0),
                    "views": m.get("_nViewCount", 0),
                    "thumb": thumb
                })

            page += 1
            time.sleep(0.05)

        self.bridge.mods_ready.emit(self.fetch_id, mods)

# -------------------------
# Releases Download Threat
# -------------------------
class DownloadThread(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)

    def __init__(self, release, juego, destino_base="Ports"):
        super().__init__()

        self.release = release
        self.juego = juego
        self.destino_base = destino_base

    def run(self):
        try:
            assets = self.release.get("assets", [])

            zips = [
                a for a in assets
                if a.get("name", "").lower().endswith(".zip")
            ]

            if not zips:
                self.status.emit("No hay ZIPs en esta release")
                return

            tag = self.release.get("tag_name", "").lower()
            nombre_release = self.release.get("name", "").lower()

            asset = next(
                (a for a in zips if "win64" in a["name"].lower()),
                None
            )

            if not asset:
                asset = next(
                    (a for a in zips if "windows" in a["name"].lower()),
                    None
                )

            if not asset:
                asset = next(
                    (
                        a for a in zips
                        if tag in a["name"].lower()
                        or nombre_release in a["name"].lower()
                    ),
                    None
                )

            if not asset:
                asset = zips[0]

            nombre = asset["name"]
            nombre_base = os.path.splitext(nombre)[0]

            destino = os.path.join(
                self.destino_base,
                self.juego,
                nombre_base
            )

            if os.path.exists(destino):
                self.finished.emit("La versión ya existe")
                return

            os.makedirs(destino, exist_ok=True)

            self.status.emit(f"Descargando {nombre}...")

            r = requests.get(
                asset["browser_download_url"],
                stream=True
            )

            total = int(r.headers.get("content-length", 0))

            buffer = io.BytesIO()

            descargado = 0

            for chunk in r.iter_content(8192):
                if chunk:
                    buffer.write(chunk)

                    descargado += len(chunk)

                    if total > 0:
                        percent = int(descargado * 100 / total)
                        self.progress.emit(percent)

            self.status.emit("Extrayendo archivos...")

            buffer.seek(0)

            with zipfile.ZipFile(buffer) as z:
                total_files = len(z.infolist())

                for i, member in enumerate(z.infolist()):

                    ruta_destino = os.path.join(
                        destino,
                        member.filename
                    )

                    if member.is_dir():
                        os.makedirs(ruta_destino, exist_ok=True)

                    else:
                        os.makedirs(
                            os.path.dirname(ruta_destino),
                            exist_ok=True
                        )

                        with z.open(member) as fuente, open(ruta_destino, "wb") as salida:
                            shutil.copyfileobj(fuente, salida)

                    extract_percent = int((i + 1) * 100 / total_files)

                    self.progress.emit(extract_percent)

            self.finished.emit(f"Instalado en:\n{destino}")

        except Exception as e:
            self.status.emit(f"Error: {e}")

# -------------------------
# GAMEBANANA WIDGET
# -------------------------            
class GameBananaWidget(QWidget):
    def __init__(self, launcher):
        super().__init__()

        self.launcher = launcher

        self.mods = []
        self.all_mods = []
        self.img_cache = {}
        
        self.mods_cache = {}
        self.current_game = None
        self.fetch_id = 0
        self.executor = ThreadPoolExecutor(max_workers=20)

        self.bridge = Bridge()
        self.bridge.mods_ready.connect(self.render)
        self.bridge.image_ready.connect(self.set_image)

        self.loading_box = QMessageBox(self)

        self.loading_box.setWindowFlag(
            Qt.FramelessWindowHint
        )

        self.loading_box.setStandardButtons(
            QMessageBox.NoButton
        )

        self.loading_box.setText(
            "Cargando mods..."
        )

        self.loading_box.setStyleSheet("""
            QMessageBox {
                background:#232323;
                border-radius:14px;
                border:1px solid #000000;
            }

            QLabel {
                background:#232323;
                color:white;
                font-size:12px;
                font-weight:bold;
            }
        """)


        self.loading_bar = QProgressBar()

        self.loading_bar.setFixedWidth(300)

        self.loading_bar.setTextVisible(False)

        self.loading_bar.setStyleSheet("""
            QProgressBar {
                background:#151515;
                border:none;
                border-radius:3px;
                min-height:6px;
                max-height:6px;
            }

            QProgressBar::chunk {
                background:#00c8ff;
                border-radius:3px;
            }
        """)


        box_layout = self.loading_box.layout()

        box_layout.addWidget(
            self.loading_bar,
            box_layout.rowCount(),
            0,
            1,
            box_layout.columnCount()
        )

        
        content_layout = QVBoxLayout(self)

        
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar mods...")
        self.search.setStyleSheet("""
            QLineEdit {
                background:#1e1e1e;
                color:white;
                border:none;
                padding:6px;
            }
        """)
        self.search.returnPressed.connect(self.filter)
        content_layout.addWidget(self.search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #000000;
                background:#282828;
            }

            QScrollBar:vertical {
                background:#1e1e1e;
                width:10px;
                margin:0px;
            }

            QScrollBar::handle:vertical {
                background:#3a3a3a;
                border-radius:5px;
                min-height:20px;
            }

            QScrollBar::handle:vertical:hover {
                background:#C83C3C;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height:0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background:none;
            }
        """)

        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)

        self.grid.setContentsMargins(
            8,
            8,
            8,
            8
        )

        self.scroll.setWidget(self.container)
        content_layout.addWidget(self.scroll)


    def load_game(self, game_name):

        self.current_game = game_name

        
        if game_name in self.mods_cache:

            self.mods = self.mods_cache[game_name]

           
            if self.grid.count() > 0:
                return

            self.render(self.fetch_id, self.mods)
            return

        
        gid = GAMEBANANA_IDS.get(game_name)

        if gid:
            self.fetch(gid)    
        
    def load_img(self, url, label):
         try:
             r = requests.get(url, timeout=10)

             if not r.content:
                 return

             self.bridge.image_ready.emit(url, r.content, label)

         except Exception as e:
             print("Error imagen:", e)   

    def fetch(self, gid):

         self.loading_bar.setRange(0, 0)

         self.loading_box.setText(
             "Renderizando..."
         )

         self.loading_box.adjustSize()

         center_pos = (
             self.window().frameGeometry().center()
             - self.loading_box.rect().center()
         )

         self.loading_box.move(
             center_pos.x() + 50,   
             center_pos.y() + 20    
         )

         self.loading_box.show()

         self.fetch_id += 1

         thread = FetchThread(gid, self.bridge)

         thread.fetch_id = self.fetch_id

         thread.start()
        
    def set_image(self, url, data, label):
         if not isValid(label):
             return

         qimg = QImage.fromData(data)

         if qimg.isNull():
             return

         pix = QPixmap.fromImage(qimg).scaled(
             CARD_W,
             IMG_H,
             Qt.KeepAspectRatioByExpanding,
             Qt.SmoothTransformation
         )

         self.img_cache[url] = pix

         label.setPixmap(pix)  

    def render(self, fetch_id, mods):

        if fetch_id != self.fetch_id:
            return

        self.mods = mods
        
        if not hasattr(self, "all_mods") or not self.all_mods:
            self.all_mods = mods.copy()
        
        if self.current_game:
            self.mods_cache[self.current_game] = mods
        

        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        total = len(mods)

        self.loading_bar.setRange(0, total)

        row = 0
        col = 0

        for i, m in enumerate(mods, start=1):

            card = self.card(m)

            self.grid.addWidget(
                card,
                row,
                col
            )
            
            self.loading_bar.setValue(i)

            QApplication.processEvents()

            col += 1

            if col >= GRID_COLS:
                col = 0
                row += 1

        self.loading_box.hide()
        
    def card(self, m):

        c = QFrame()

        c.setFixedSize(CARD_W, CARD_H)

        c.setStyleSheet("""
            QFrame {
                background:#1b1b1b;
                border:1px solid #2f2f2f;
                border-radius:14px;
            }
        """)

        v = QVBoxLayout(c)

        v.setContentsMargins(0,0,0,0)
        v.setSpacing(0)
        
        img = QLabel()

        img.setFixedHeight(IMG_H)

        img.setAlignment(Qt.AlignCenter)

        img.setStyleSheet("""
            background:#111;
            border-top-left-radius:14px;
            border-top-right-radius:14px;
        """)

        v.addWidget(img)

        body = QWidget()

        body.setStyleSheet("""
            background:#1b1b1b;
            border:none;
        """)

        body_layout = QVBoxLayout(body)

        body_layout.setContentsMargins(
            10,
            8,
            10,
            10
        )

        body_layout.setSpacing(3)

        title = QLabel()

        title.setText(
            title.fontMetrics().elidedText(
                m["name"],
                Qt.ElideRight,
                CARD_W - 30
            )
        )

        title.setToolTip(
            m["name"]
        )

        title.setFixedHeight(18)

        title.setStyleSheet("""
            color:white;
            font-size:10px;
            font-weight:700;
        """)

        body_layout.addWidget(title)

        author_row = QWidget()

        author_layout = QHBoxLayout(author_row)

        author_layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        author_layout.setSpacing(0)

        author = QLabel(
            f"por {m['author']}"
        )

        author.setStyleSheet("""
            color:#8d8d8d;
            font-size:9px;
        """)

        badge_text = (
            "MOD"
            if m["type"] == "Mod"
            else "WIP"
        )

        badge_color = (
            "#00c8ff"
            if m["type"] == "Mod"
            else "#ff9800"
        )

        badge = QLabel(
            badge_text
        )

        badge.setStyleSheet(f"""
            QLabel {{
                background:#2b2b2b;
                color:{badge_color};
                border-radius:4px;
                padding:1px 3px;
                font-size:8px;
                font-weight:700;
            }}
        """)

        author_layout.addWidget(author)

        badge.setFixedHeight(30)

        author_layout.addStretch()

        author_layout.addWidget(badge)

        body_layout.addWidget(author_row)

        stats = QFrame()

        stats.setFixedHeight(34)
        stats.setMaximumWidth(140)

        stats.setStyleSheet("""
            QFrame {
                background:#242424;
                border:1px solid #3a3a3a;
                border-radius:17px;
            }
        """)

        stats_layout = QHBoxLayout(stats)

        stats_layout.setContentsMargins(
            10,
            4,
            10,
            4
        )

        stats_layout.setSpacing(10)

        stats_layout.setAlignment(
            Qt.AlignCenter
        )

        likes = QLabel(
            f"<span style='color:#ff4d4d;'>❤</span> {m['likes']:,}"
        )

        comments = QLabel(
            f"💬 {m['posts']:,}"
        )

        views = QLabel(
            f"👁 {m['views']:,}"
        )

        for lbl in (
            likes,
            comments,
            views
        ):
            lbl.setAlignment(Qt.AlignCenter)

            lbl.setStyleSheet("""
                color:white;
                font-size:9px;
                font-weight:700;
                border:none;
                background:transparent;
            """)

        stats_layout.addWidget(likes)
        stats_layout.addWidget(comments)
        stats_layout.addWidget(views)

        body_layout.addSpacing(8)

        body_layout.addWidget(
            stats,
            alignment=Qt.AlignCenter
        )

        body_layout.addSpacing(8)

        btn = QPushButton("👁")

        btn.setFixedHeight(30)

        btn.setCursor(
            Qt.PointingHandCursor
        )

        btn.setStyleSheet("""
            QPushButton {
                background:#C83C3C;
                color:white;
                border:none;
                border-radius:8px;
                font-size:13px;
                font-weight:bold;
            }

            QPushButton:hover {
                background:#e04b4b;
            }

            QPushButton:pressed {
                background:#b53030;
            }
            QPushButton:focus {
                    outline:none;
                    border:none;
            }
        """)

        body_layout.addWidget(btn)

        v.addWidget(body)

        btn.clicked.connect(
            lambda _,
            mod_id=m["id"],
            mod_type=m["type"]:
            self.launcher.abrir_detalles_mod(
                mod_id,
                mod_type
            )
        )

        if m["thumb"]:

            if m["thumb"] in self.img_cache:

                img.setPixmap(
                    self.img_cache[
                        m["thumb"]
                    ]
                )

            else:

                self.executor.submit(
                    self.load_img,
                    m["thumb"],
                    img
                )

        return c

    def clear_cards(self):

        for i in reversed(range(self.grid.count())):

            w = self.grid.itemAt(i).widget()

            if w:
                w.deleteLater()
                
    def filter(self):

        texto = self.search.text().strip().lower()

        if texto == "":
            self.render(self.fetch_id, self.all_mods)
            return

        filtrados = [
            m for m in self.all_mods
            if texto in (m["name"] or "").lower()
        ]

        self.render(self.fetch_id, filtrados)



    def obtener_detalles_mod(self, mod_id, mod_type):
        try:
            main = requests.get(
                f"https://gamebanana.com/apiv11/{mod_type}/{mod_id}",
                params={"_csvProperties": "@gbprofile"},
                timeout=10
            ).json()

            profile = requests.get(
                  f"https://gamebanana.com/apiv11/{mod_type}/{mod_id}/ProfilePage",
                  timeout=10
            ).json()

        except:
            return None

        images = []
        for img in main.get("_aPreviewMedia", {}).get("_aImages", []):
            b = img.get("_sBaseUrl")
            f = img.get("_sFile800") or img.get("_sFile")
            if b and f:
                images.append(f"{b}/{f}")

        description = profile.get("_sText") or "Sin descripción disponible."

        files = []
        for f in main.get("_aFiles", []):
            url = f.get("_sDownloadUrl")
            name = f.get("_sFile")
            if url and name:
                files.append((name, url))

        return images, description, files

        
# -------------------------
# HM Launcher
# -------------------------
class HM64Launcher(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("HM Lanzador")
        self.setGeometry(200, 200, 750, 520)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

        self.juego_activo = 0
        self.tab_activa = 1
        self.mod_images = []
        self.mod_image_index = 0
        self.mod_image_cache = {}
        self.mod_downloads = []

        self._dragging = False
        self._drag_pos = None
        self.releases_loaded = False

        self.releases_data = []
        self.releases_cache = {}
        self.active_installations = {}
        self.load_config()

        self.game_process = None
        self.process_timer = QTimer(self)
        self.process_timer.timeout.connect(self.check_game_process)
        self.process_timer.start(1000)
                
        self._build_ui()
        self.loader = ReleasesLoader()

        self.loader.finished_loading.connect(
            self.on_releases_loaded
        )

        self.loader.start()
        self.set_game(0)
        self.set_tab(0)
        self.update_active_buttons()
        self.start_update_timer()
         
    # -------------------------
    # UI ROOT
    # -------------------------
    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background-color: {COLOR_BG};")
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)

        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_center())

        layout.addLayout(body)

    # -------------------------
    # HEADER
    # -------------------------
    def _build_header(self):
        self.header = QFrame()
        self.header.setFixedHeight(60)
        self.header.setStyleSheet("background-color:#0a0a0a;")

        layout = QHBoxLayout(self.header)
        layout.setContentsMargins(15, 0, 20, 0)  
        layout.setSpacing(0)

        logo_layout = QHBoxLayout()
        logo_layout.setSpacing(2)

        self.label_hm = QLabel(" H")
        self.label_64 = QLabel("M")
        self.label_sub = QLabel(" Lanzador v2.0")

        self.label_hm.setStyleSheet("""
            color:#00c8ff;
            font-size:30px;
            font-weight:800;
        """)

        self.label_64.setStyleSheet("""
            color:#ff3232;
            font-size:30px;
            font-weight:800;
        """)

        self.label_sub.setStyleSheet("""
            color:white;
            font-size:14px;
            margin-left:10px;
        """)

        logo_layout.addWidget(self.label_hm)
        logo_layout.addWidget(self.label_64)
        logo_layout.addSpacing(10)
        logo_layout.addWidget(self.label_sub)

        logo_container = QWidget()
        logo_container.setLayout(logo_layout)

        layout.addWidget(logo_container)

        layout.addStretch()

        # -------------------------
        # BOTONES MIN / CLOSE
        # -------------------------
        btn_min = QPushButton("-")
        btn_close = QPushButton("X")

        btn_min.setFixedSize(35, 30)
        btn_close.setFixedSize(35, 30)

        btn_min.setStyleSheet("""
            QPushButton {
                background:#444;
                color:white;
                border-radius:4px;
                font-size:14px;
                margin-right:6px;
            }
            QPushButton:hover {
                background:#666;
            }
            QPushButton:focus {
                    outline:none;
                    border:none;
            }
        """)

        btn_close.setStyleSheet("""
            QPushButton {
                background:#c83c3c;
                color:white;
                border-radius:6px;
                font-size:14px;
            }
            QPushButton:hover {
                background:#ff6666;
            }
            QPushButton:focus {
                    outline:none;
                    border:none;
            }
        """)

        btn_min.clicked.connect(self.showMinimized)
        btn_close.clicked.connect(self.close)

        layout.addWidget(btn_min)
        layout.addWidget(btn_close)

        return self.header

    # -------------------------
    # SIDEBAR
    # -------------------------
    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(120)
        sidebar.setStyleSheet("background-color:#0a0a0a;")

        layout = QVBoxLayout(sidebar)

        # -----------------
        # BOTONES JUEGOS
        # -----------------
        self.game_buttons = []
        for i, g in enumerate(JUEGOS):
            btn = QPushButton(g)
            self.game_buttons.append(btn)
            btn.setStyleSheet("""
                QPushButton {
                    color:white;
                    background:#111;
                    border-radius:6px;
                    padding:6px;
                }
                QPushButton:hover,
                QPushButton[active="true"] {
                    background:#444;
                }
                QPushButton:focus {
                    outline:none;
                    border:none;
                }
            """)
            btn.clicked.connect(lambda _, x=i: self.set_game(x))
            layout.addWidget(btn)

        layout.addStretch()

        self.btn_config = QPushButton("⚙")
        btn_config = self.btn_config
        btn_config.setFixedSize(60, 60)
        btn_config.setStyleSheet("""
            QPushButton {
                color:white;
                background:#111;
                border-radius:12px;
                font-size:20px;
            }
            QPushButton:hover,
            QPushButton[active="true"] {
                background:#444;
            }
            QPushButton:focus {
                    outline:none;
                    border:none;
            }
        """)
        btn_config.clicked.connect(self.open_config)

        layout.addWidget(btn_config, alignment=Qt.AlignmentFlag.AlignCenter)

        return sidebar

    # -------------------------
    # CENTER
    # -------------------------
    def _build_center(self):
        center = QFrame()
        center.setStyleSheet("background-color:#282828;")

        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs_bar = QHBoxLayout()
        tabs_bar.setSpacing(0)
        tabs_bar.setContentsMargins(0, 0, 0, 0)

        self.tab_buttons = []
        for i, t in enumerate(TABS):
            btn = QPushButton(t)
            self.tab_buttons.append(btn)
            btn.setStyleSheet("""
                QPushButton {
                    color:white;
                    background:#191919;
                    padding:12px;
                    border-radius:0px;
                    border-bottom:3px solid transparent;
                }
                QPushButton:hover,
                QPushButton[active="true"] {
                    background:#191919;
                    border-bottom:3px solid #00c8ff;
                }
                QPushButton:focus {
                    outline:none;
                }
            """)
            btn.clicked.connect(lambda _, x=i: self.set_tab(x))
            tabs_bar.addWidget(btn)

        layout.addLayout(tabs_bar)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.page_general())
        self.stack.addWidget(self.page_versions())
        self.stack.addWidget(self.page_mods())

        self.gamebanana_page = self.page_gamebanana()
        self.stack.addWidget(self.gamebanana_page)

        self.mod_details_page = self.page_mod_details()
        self.stack.addWidget(self.mod_details_page)

        self.stack.addWidget(self.page_config())

        layout.addWidget(self.stack)

        return center  

    # -------------------------
    # GENERAL
    # -------------------------
    def page_general(self):
         w = QWidget()

         self.general_page = w

         self.bg_label = QLabel(w)
         self.bg_label.setScaledContents(False)
         self.bg_label.lower()

         self.bg_pixmap = QPixmap()

         self.bg_label.setMinimumSize(0, 0)
         self.bg_label.setMaximumSize(9999, 9999)

         self.dark_overlay = QFrame(w)
         self.dark_overlay.setStyleSheet(
             "background-color: rgba(0, 0, 0, 120);"
         )
         self.dark_overlay.lower()

         layout = QVBoxLayout(w)

         layout.setContentsMargins(18, 12, 18, 18)
         
         self.label = QLabel(
             f"Instalación activa: {JUEGOS[self.juego_activo]}"
         )

         self.label.setStyleSheet("""
             background:transparent;
             color:white;
             font-size:14px;
             font-weight:bold;
         """)

         layout.addWidget(
             self.label,
             alignment=Qt.AlignmentFlag.AlignTop |
                       Qt.AlignmentFlag.AlignLeft
         )
         
         layout.addStretch()

         
         self.play_btn = QPushButton("▶")
         btn = self.play_btn

         btn.setFixedSize(120, 42)
         
         btn.clicked.connect(self.launch_active_game)

         btn.setStyleSheet("""
             QPushButton {
                 background:#c83c3c;
                 color:black;
                 padding:10px;
                 border-radius:10px;
                 font-size:45px;
                 font-weight:800;
             }

             QPushButton:hover {
                 background:#ff6666;
             }
             QPushButton:focus {
                    outline:none;
                    border:none;
             }
         """)

         bottom = QHBoxLayout()

         bottom.setContentsMargins(0, 0, 25, 20)

         bottom.addStretch()

         bottom.addWidget(
             btn,
             alignment=Qt.AlignmentFlag.AlignRight |
                       Qt.AlignmentFlag.AlignBottom
         )

         layout.addLayout(bottom)

         self.update_background()

         return w

    # -------------------------
    # VERSIONES
    # -------------------------
    def page_versions(self):

         w = QWidget()

         root = QVBoxLayout(w)
         root.setContentsMargins(12, 12, 12, 12)

         self.version_scroll = QScrollArea()

         self.version_scroll.setWidgetResizable(True)

         self.version_scroll.setStyleSheet("""
             QScrollArea {
                 border:none;
                 background:#191919;
             }

             QScrollBar:vertical {
                 background:#1e1e1e;
                 width:8px;
                 margin:0px;
             }

             QScrollBar::handle:vertical {
                 background:#3a3a3a;
                 border-radius:4px;
                 min-height:20px;
             }

             QScrollBar::handle:vertical:hover {
                 background:#00c8ff;
             }

             QScrollBar::add-line:vertical,
             QScrollBar::sub-line:vertical {
                 height:0px;
             }

             QScrollBar::add-page:vertical,
             QScrollBar::sub-page:vertical {
                 background:none;
             }
         """)

         self.version_container = QWidget()

         self.version_layout = QVBoxLayout(
             self.version_container
         )

         self.version_layout.setSpacing(10)

         self.version_layout.setContentsMargins(
             0, 0, 0, 0
         )

         self.version_layout.addStretch()

         self.version_scroll.setWidget(
             self.version_container
         )

         root.addWidget(self.version_scroll)

         return w
    
    # -------------------------
    # MODS
    # -------------------------
    def page_mods(self):

         w = QWidget()

         root = QVBoxLayout(w)
         root.setContentsMargins(12, 12, 12, 12)

         self.mods_scroll = QScrollArea()
         self.mods_scroll.setWidgetResizable(True)

         self.mods_scroll.setStyleSheet("""
             QScrollArea {
                 border:none;
                 background:#191919;
             }

             QScrollBar:vertical {
                 background:#1e1e1e;
                 width:8px;
                 margin:0px;
             }

             QScrollBar::handle:vertical {
                 background:#3a3a3a;
                 border-radius:4px;
                 min-height:20px;
             }

             QScrollBar::handle:vertical:hover {
                 background:#00c8ff;
             }

             QScrollBar::add-line:vertical,
             QScrollBar::sub-line:vertical {
                 height:0px;
             }

             QScrollBar::add-page:vertical,
             QScrollBar::sub-page:vertical {
                 background:none;
             }
         """)

         self.mods_container = QWidget()

         self.mods_layout = QVBoxLayout(self.mods_container)

         self.mods_layout.setSpacing(10)

         self.mods_layout.setContentsMargins(
             0, 0, 0, 0
         )

         self.mods_layout.addStretch()

         self.mods_scroll.setWidget(
             self.mods_container
         )

         root.addWidget(self.mods_scroll)

         self.load_mods()

         return w

    # -------------------------
    # Gamebanana 
    # -------------------------   
    def page_gamebanana(self):
        return GameBananaWidget(self)
    
    # -------------------------
    # Gamebanana details
    # -------------------------
    def page_mod_details(self):

      root = QWidget()

      root_layout = QVBoxLayout(root)

      root_layout.setContentsMargins(
          0, 0, 0, 0
      )

      # -------------------------
      # SCROLL
      # -------------------------

      scroll = QScrollArea()

      scroll.setWidgetResizable(True)

      scroll.setStyleSheet("""
          QScrollArea {
              border:none;
              background:#282828;
          }

          QScrollBar:vertical {
              background:#1e1e1e;
              width:10px;
              margin:0px;
          }

          QScrollBar::handle:vertical {
              background:#3a3a3a;
              border-radius:5px;
              min-height:20px;
          }

          QScrollBar::handle:vertical:hover {
              background:#C83C3C;
          }

          QScrollBar::add-line:vertical,
          QScrollBar::sub-line:vertical {
              height:0px;
          }

          QScrollBar::add-page:vertical,
          QScrollBar::sub-page:vertical {
              background:none;
          }
      """)

      container = QWidget()

      layout = QVBoxLayout(container)

      layout.setContentsMargins(
          12, 12, 12, 12
      )

      layout.setSpacing(10)

      # -------------------------
      # IMAGEN
      # -------------------------

      self.mod_image = QLabel()

      self.mod_image.setFixedSize(520, 280)

      self.mod_image.setAlignment(
          Qt.AlignCenter
      )

      self.mod_image.setMouseTracking(True)

      self.mod_image.setStyleSheet("""
          background:#1e1e1e;
          border:1px solid #000000;
          border-radius:10px;
      """)

      # -------------------------
      # BOTONES SOBRE IMAGEN
      # -------------------------

      self.prev_img_btn = QPushButton(
          "◀",
          self.mod_image
      )

      self.next_img_btn = QPushButton(
          "▶",
          self.mod_image
      )

      for b in (
          self.prev_img_btn,
          self.next_img_btn
      ):

          b.setFixedSize(42, 42)

          b.setStyleSheet("""
              QPushButton {
                  background:rgba(0,0,0,120);
                  color:white;
                  border:none;
                  border-radius:21px;
                  font-size:15px;
                  font-weight:bold;
              }
              QPushButton:hover {
                  background:#C83C3C;
              }
              QPushButton:focus {
                    outline:none;
                    border:none;
              }
          """)

          b.hide()

      self.prev_img_btn.move(
          10,
          119
      )

      self.next_img_btn.move(
          468,
          119
      )

      self.mod_image.enterEvent = lambda e: (
          self.prev_img_btn.show(),
          self.next_img_btn.show()
      )

      self.mod_image.leaveEvent = lambda e: (
          self.prev_img_btn.hide(),
          self.next_img_btn.hide()
      )

      self.prev_img_btn.clicked.connect(
          self.prev_mod_image
      )

      self.next_img_btn.clicked.connect(
          self.next_mod_image
      )

      layout.addWidget(
          self.mod_image,
          alignment=Qt.AlignCenter
      )

      # -------------------------
      # DESCRIPCIÓN
      # -------------------------

      self.mod_desc = QTextEdit()

      self.mod_desc.setReadOnly(True)

      self.mod_desc.setMinimumHeight(220)

      self.mod_desc.setStyleSheet("""
          QTextEdit {
              background:#1e1e1e;
              color:white;
              border:1px solid #000000;
              padding:6px;
          }
      """)

      layout.addWidget(self.mod_desc)

      # -------------------------
      # ARCHIVOS
      # -------------------------

      self.mod_files_container = QWidget()

      self.mod_files_layout = QVBoxLayout(
         self.mod_files_container
      )

      self.mod_files_layout.setContentsMargins(
         0, 0, 0, 0
      )

      self.mod_files_layout.setSpacing(10)

      layout.addWidget(
         self.mod_files_container
      )

      layout.addStretch()

      scroll.setWidget(container)

      root_layout.addWidget(scroll)

      return root
    
    # -------------------------
    # Config
    # ------------------------- 
    def open_config(self):
        self.stack.setCurrentIndex(5)
        
        for btn in self.tab_buttons:
            btn.setProperty("active", False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.btn_config.setProperty("active", True)
        self.btn_config.style().unpolish(self.btn_config)
        self.btn_config.style().polish(self.btn_config)

    def page_config(self):

          w = QWidget()

          layout = QVBoxLayout(w)

          layout.setContentsMargins(
              30, 30, 30, 30
          )

          interval_label = QLabel(
              "Comprobar nuevas versiones cada (minutos)"
          )

          interval_label.setStyleSheet("""
              color:white;
              font-size:13px;
              font-weight:bold;
          """)

          layout.addWidget(interval_label)

          self.interval_spin = QSpinBox()

          self.interval_spin.setRange(
              1,
              1440
          )

          self.interval_spin.setValue(
              self.config_data.get(
                  "update_check_interval",
                  60
              )
          )
          self.interval_spin.setFixedWidth(80)
          self.interval_spin.setStyleSheet("""
              QSpinBox {
                  background:#1e1e1e;
                  color:white;
                  border:none;
                  padding:6px;
              }
          """)

          layout.addWidget(self.interval_spin)

          save_btn = QPushButton("💾")
          save_btn.setFixedWidth(120)
          save_btn.setStyleSheet("""
              QPushButton {
                  background:#3a3a3a;
                  color:black;
                  border:none;
                  border-radius:8px;
                  padding:8px;
                  font-weight:bold;
              }

              QPushButton:hover {
                  background:#444;
              }
              QPushButton:focus {
                    outline:none;
                    border:none;
              }
          """)

          save_btn.clicked.connect(
              self.save_update_settings
          )

          layout.addWidget(save_btn)

          layout.addStretch()

          return w 

    # -------------------------
    # Logic general
    # -------------------------
    
    def update_general_label(self):

         juego = JUEGOS[self.juego_activo]

         active = self.active_installations.get(juego)

         if active:

             version = active.get("version", "Desconocida")

             self.label.setText(
                 f"Instalación activa: {version}"
             )

         else:

             self.label.setText(
                 "Instalación activa: ninguna"
             )

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if hasattr(self, "bg_label") and hasattr(self, "bg_pixmap"):
            rect = self.stack.currentWidget().rect()
            self.bg_label.setGeometry(rect)
            self.dark_overlay.setGeometry(rect)

            scaled = self.bg_pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x_offset = 0
            y_offset = 0
            x = (scaled.width() - rect.width()) // 2 + x_offset
            y = (scaled.height() - rect.height()) // 2 + y_offset
            x = max(0, min(x, scaled.width() - rect.width()))
            y = max(0, min(y, scaled.height() - rect.height()))

            cropped = scaled.copy(x, y, rect.width(), rect.height())

            self.bg_label.setPixmap(cropped)


    def update_background(self):

         ruta = os.path.join(
             "assets",
             f"background{self.juego_activo + 1}.png"
         )

         self.bg_pixmap = QPixmap(ruta)

         if self.bg_pixmap.isNull():
             return

         rect = self.general_page.rect()

         if rect.width() <= 0 or rect.height() <= 0:
             return

         scaled = self.bg_pixmap.scaled(
             rect.size(),
             Qt.AspectRatioMode.KeepAspectRatioByExpanding,
             Qt.TransformationMode.SmoothTransformation
         )

         x = (scaled.width() - rect.width()) // 2
         y = (scaled.height() - rect.height()) // 2

         cropped = scaled.copy(
             x,
             y,
             rect.width(),
             rect.height()
         )

         self.bg_label.setGeometry(rect)
         self.dark_overlay.setGeometry(rect)

         self.bg_label.setPixmap(cropped)
            
    def launch_active_game(self):

         if self.game_process and self.game_process.poll() is None:
             self.game_process.terminate()
             self.game_process = None
             self.play_btn.setText("▶")
             self.play_btn.setStyleSheet("""
                 QPushButton {
                     background:#c83c3c;
                     color:black;
                     padding:10px;
                     border-radius:10px;
                     font-size:45px;
                     font-weight:800;
                 }

                 QPushButton:hover {
                     background:#ff6666;
                 }
                 QPushButton:focus {
                        outline:none;
                        border:none;
                 }
             """)
             return
            
         juego = JUEGOS[self.juego_activo]

         active = self.active_installations.get(juego)

         if not active:
             QMessageBox.warning(
                 self,
                 "Sin instalación",
                 "No hay una instalación activa para este juego."
             )
             return

         base_path = active.get("path")

         if not base_path or not os.path.exists(base_path):
             QMessageBox.warning(
                 self,
                 "Ruta inválida",
                 "La instalación activa no existe."
             )
             return

         exe_files = []

         for root, dirs, files in os.walk(base_path):

             for file in files:

                 if file.lower().endswith(".exe"):

                     
                     lower = file.lower()

                     if any(x in lower for x in [
                         "updater",
                         "crash",
                         "installer",
                         "setup"
                     ]):
                         continue

                     exe_files.append(
                         os.path.join(root, file)
                     )

         if not exe_files:

             QMessageBox.warning(
                 self,
                 "EXE no encontrado",
                 "No se encontró ningún ejecutable."
             )
             return

         exe_path = exe_files[0]

         try:

             self.game_process = subprocess.Popen(
                 exe_path,
                 cwd=os.path.dirname(exe_path)
             )

             self.play_btn.setText("■")
             self.play_btn.setStyleSheet("""
                 QPushButton {
                     background:#c83c3c;
                     color:black;
                     padding:10px;
                     border-radius:10px;
                     font-size:25px;
                     font-weight:750;
                 }

                 QPushButton:hover {
                     background:#ff6666;
                 }
                 QPushButton:focus {
                        outline:none;
                        border:none;
                 }
             """)

             

         except Exception as e:

             QMessageBox.critical(
                 self,
                 "Error",
                 f"No se pudo ejecutar:\n\n{e}"
             )


    def check_game_process(self):

        if self.game_process is None:
            return

        if self.game_process.poll() is not None:
            self.game_process = None
            self.play_btn.setText("▶")
            self.play_btn.setStyleSheet("""
                 QPushButton {
                     background:#c83c3c;
                     color:black;
                     padding:10px;
                     border-radius:10px;
                     font-size:45px;
                     font-weight:800;
                 }

                 QPushButton:hover {
                     background:#ff6666;
                 }
                 QPushButton:focus {
                        outline:none;
                        border:none;
                 }
             """)

            
    # -------------------------
    # Logic releases
    # -------------------------
    def create_release_card(self, rel, instalado, activa=False):

         card = QFrame()

         card.setFixedSize(590, 82)

         card.setStyleSheet("""
             QFrame {
                 background:#202020;
                 border-radius:14px;
             }

             QFrame:hover {
                 background:#202020;
             }
         """)

         layout = QHBoxLayout(card)

         layout.setContentsMargins(
             16, 12, 16, 12
         )

         # -------------------------
         # INFO
         # -------------------------

         info = QVBoxLayout()

         name = rel["name"] or rel["tag_name"]

         title = QLabel(name)

         title.setStyleSheet("""
             color:white;
             font-size:13px;
             font-weight:600;
         """)


         if activa:
              status_text = "Instalación activa"
         elif instalado:
              status_text = "Instalado"
         else:
              status_text = "No instalado"

         subtitle = QLabel(status_text)
         
         subtitle.setStyleSheet("""
             color:#9a9a9a;
             font-size:11px;
         """)

         info.addWidget(title)
         info.addWidget(subtitle)

         layout.addLayout(info)

         layout.addStretch()

         # -------------------------
         # PROGRESS
         # -------------------------

         progress = QProgressBar()

         progress.setFixedWidth(90)
         progress.setFixedHeight(6)

         progress.setTextVisible(False)

         progress.setStyleSheet("""
             QProgressBar {
                 background:#151515;
                 border:none;
                 border-radius:3px;
             }

             QProgressBar::chunk {
                 background:#00c8ff;
                 border-radius:3px;
             }
         """)

         progress.hide()

         layout.addWidget(progress)

         # -------------------------
         # ACCIONES
         # -------------------------

         actions = QHBoxLayout()
         actions.setSpacing(6)

         # -------------------------
         # BOTÓN PRINCIPAL
         # -------------------------

         btn = QPushButton()

         btn.setFixedSize(36, 36)

         if instalado:

             btn.setText("▶")

             if activa:
                 btn_color = "#ff9800"
                 btn_hover = "#ffb74d"
             else:
                 btn_color = "#00c853"
                 btn_hover = "#19e06c"

             btn.setStyleSheet(f"""
                   QPushButton {{
                       background:{btn_color};
                       color:black;
                       border:none;
                       border-radius:10px;
                       font-size:15px;
                       font-weight:bold;
                   }}

                   QPushButton:hover {{
                       background:{btn_hover};
                   }}
               """)

             # -------------------------
             # ACTIVAR INSTALACIÓN
             # -------------------------

             def activate_version():

                 juego = JUEGOS[self.juego_activo]

                 assets = rel.get("assets", [])

                 base_path = os.path.join("Ports", juego)

                 for asset in assets:

                     asset_name = asset.get("name", "")

                     if not asset_name.lower().endswith(".zip"):
                         continue

                     carpeta = os.path.splitext(
                         asset_name
                     )[0]

                     ruta = os.path.join(
                         base_path,
                         carpeta
                     )

                     if os.path.exists(ruta):

                         version = (
                             rel["name"]
                             or rel["tag_name"]
                         )

                         self.set_active_installation(
                             juego,
                             ruta,
                             version
                         )
                         
                         self.load_versions()


                         print(
                             "Versión activa:",
                             ruta
                         )

                         break

             btn.clicked.connect(
                 activate_version
             )

         else:

             btn.setText("⭳")

             btn.setStyleSheet("""
                 QPushButton {
                     background:#c83c3c;
                     color:black;
                     border:none;
                     border-radius:10px;
                     font-size:16px;
                     font-weight:bold;
                 }

                 QPushButton:hover {
                     background:#e04b4b;
                 }
                 QPushButton:focus {
                    outline:none;
                    border:none;
                 }
             """)

             btn.clicked.connect(
                 lambda: self.download_release(
                     rel,
                     progress,
                     subtitle,
                     btn
                 )
             )

         actions.addWidget(btn)

         # -------------------------
         # BOTÓN CARPETA
         # -------------------------

         if instalado:

             folder_btn = QPushButton("📂")

             folder_btn.setFixedSize(36, 36)

             folder_btn.setStyleSheet("""
                 QPushButton {
                     background:#3a3a3a;
                     color:white;
                     border:none;
                     border-radius:10px;
                     font-size:14px;
                 }

                 QPushButton:hover {
                     background:#444;
                 }
                 QPushButton:focus {
                    outline:none;
                    border:none;
                 }
             """)

             def open_folder():

                 juego = JUEGOS[self.juego_activo]

                 assets = rel.get("assets", [])

                 base_path = os.path.join(
                     "Ports",
                     juego
                 )

                 for asset in assets:

                     name = asset.get("name", "")

                     if not name.lower().endswith(".zip"):
                         continue

                     carpeta = os.path.splitext(
                         name
                     )[0]

                     ruta = os.path.join(
                         base_path,
                         carpeta
                     )

                     if os.path.exists(ruta):
                         os.startfile(ruta)

             folder_btn.clicked.connect(
                 open_folder
             )

             actions.addWidget(folder_btn)

             # -------------------------
             # BOTÓN BORRAR
             # -------------------------

             delete_btn = QPushButton("🗑")

             delete_btn.setFixedSize(36, 36)

             delete_btn.setStyleSheet("""
                 QPushButton {
                     background:#3a3a3a;
                     color:white;
                     border:none;
                     border-radius:10px;
                     font-size:14px;
                 }

                 QPushButton:hover {
                     background:#c83c3c;
                 }
                 QPushButton:focus {
                    outline:none;
                    border:none;
                 }
             """)

             delete_btn.clicked.connect(
                 lambda: self.delete_version(rel)
             )

             actions.addWidget(delete_btn)

         layout.addLayout(actions)

         return card
        
    def preload_releases(self):
         print("Precargando releases...")

         for juego, repo in REPOS.items():

             try:
                 r = requests.get(
                     f"https://api.github.com/repos/{repo}/releases?per_page=100",
                     timeout=15
                 )

                 data = r.json()

                 self.releases_cache[juego] = data
                 self.check_new_releases(juego, data)

                 print(f"[OK] {juego}: {len(data)} releases")

             except Exception as e:
                 print(f"[ERROR] {juego}:", e)

                 self.releases_cache[juego] = []
                 

         self.releases_loaded = True
         self.load_versions()

    def load_versions(self):

         if not self.releases_loaded:
             return

         while self.version_layout.count():

             item = self.version_layout.takeAt(0)

             widget = item.widget()

             if widget:
                 widget.deleteLater()

         juego = JUEGOS[self.juego_activo]

         data = self.releases_cache.get(
             juego,
             []
         )

         base_path = os.path.join(
             "Ports",
             juego
         )

         for rel in data:

             assets = rel.get("assets", [])

             instalado = False
             activa = False

             for asset in assets:

                 asset_name = asset.get(
                     "name",
                     ""
                 )

                 if not asset_name.lower().endswith(".zip"):
                     continue

                 carpeta = os.path.splitext(
                     asset_name
                 )[0]

                 ruta = os.path.join(
                     base_path,
                     carpeta
                 )

                 if os.path.exists(ruta):
                        instalado = True

                        active = self.active_installations.get(juego)

                        if active:
                            active_path = active.get("path", "").replace("\\", "/")
                            current_path = ruta.replace("\\", "/")

                            if active_path == current_path:
                                activa = True

                        break

             card = self.create_release_card(
                 rel,
                 instalado,
                 activa
             )

             self.version_layout.addWidget(card)

         self.version_layout.addStretch()
         

    def download_release(
         self,
         rel,
         progress,
         subtitle,
         btn
     ):

         juego = JUEGOS[self.juego_activo]

         self.thread = DownloadThread(
             rel,
             juego
         )

         progress.show()

         self.thread.progress.connect(
             progress.setValue
         )

         self.thread.status.connect(
             subtitle.setText
         )

         def finished(msg):

             subtitle.setText("Instalado")

             btn.setText("▶")

             btn.setStyleSheet("""
                 QPushButton {
                     background:#00c853;
                     color:black;
                     border:none;
                     border-radius:10px;
                     font-size:15px;
                     font-weight:bold;
                 }

                 QPushButton:hover {
                     background:#19e06c;
                 }
                 QPushButton:focus {
                    outline:none;
                    border:none;
                 }
             """)

             progress.hide()

             self.load_versions()

         self.thread.finished.connect(
             finished
         )

         self.thread.start()


    def delete_version(self, rel):

         name = rel["name"] or rel["tag_name"]

         msgbox = QMessageBox(self)
         layout = msgbox.layout()
         layout.setContentsMargins(0, 10, 18, 10)  
         msgbox.setWindowFlag(Qt.FramelessWindowHint)
         msgbox.setText(
             f"¿Seguro que quieres borrar la instalación?\n\n{name}"
         )

         msgbox.setStandardButtons(
             QMessageBox.StandardButton.Yes |
             QMessageBox.StandardButton.No
         )

         msgbox.setDefaultButton(
             QMessageBox.StandardButton.No
         )

         msgbox.setStyleSheet("""
             QMessageBox {
                 background:#232323;
                 border-radius:14px;
                 border:1px solid #000000;
             }

             QLabel {
                 color:white;
                 font-size:12px;
                 font-weight:bold;
             }

             QPushButton {
                 background:#3a3a3a;
                 color:white;
                 border:none;
                 border-radius:8px;
                 padding:8px 14px;
                 min-width:70px;
             }

             QPushButton:hover {
                 background:#c83c3c;
             }
             QPushButton:focus {
                    outline:none;
                    border:none;
             }
         """)

         reply = msgbox.exec()

         if reply != QMessageBox.StandardButton.Yes:
             return

         juego = JUEGOS[self.juego_activo]

         assets = rel.get("assets", [])

         base_path = os.path.join(
             "Ports",
             juego
         )

         for asset in assets:

             asset_name = asset.get(
                 "name",
                 ""
             )

             if not asset_name.lower().endswith(".zip"):
                 continue

             carpeta = os.path.splitext(
                 asset_name
             )[0]

             ruta = os.path.join(
                 base_path,
                 carpeta
             )

             if os.path.exists(ruta):

                   try:

                       normalized_ruta = ruta.replace("\\", "/")

                       active = self.active_installations.get(juego)

                       if active:

                           active_path = active.get(
                               "path",
                               ""
                           ).replace("\\", "/")

                           if active_path == normalized_ruta:

                               self.active_installations[juego] = None

                               self.save_config()
                               self.update_general_label()
                               self.load_mods()

                       shutil.rmtree(ruta)

                   except Exception as e:
                       print("Error borrando:", e)

         self.load_versions()
         
    def set_active_installation(self, juego, path, version):

         normalized_path = path.replace("\\", "/")

         self.active_installations[juego] = {
             "path": normalized_path,
             "version": version
         }

         self.save_config()
         self.update_general_label()
         self.load_mods()

    def download_selected_version(self):
         row = self.version_list.currentRow()

         if row < 0:
             self.status_label.setText("Selecciona una versión")
             return

         rel = self.releases_data[row]

         juego = JUEGOS[self.juego_activo]

         self.thread = DownloadThread(rel, juego)

         self.thread.progress.connect(self.progress.setValue)
         self.thread.status.connect(self.status_label.setText)
         self.thread.finished.connect(self.status_label.setText)
         self.thread.finished.connect(self.load_versions)

         self.progress.setValue(0)

         self.thread.start()


    def check_new_releases(self, juego, releases):

         if not releases:
             return

         latest = releases[0]

         latest_date = latest.get("published_at")

         if not latest_date:
             return

         saved_dates = self.config_data.get(
             "release_dates",
             {}
         )

         old_date = saved_dates.get(juego)

         if old_date is None:

             saved_dates[juego] = latest_date

             self.config_data["release_dates"] = saved_dates

             self.save_config()

             return
         
         if latest_date != old_date:
             
             release_name = (
                 latest.get("name")
                 or latest.get("tag_name")
                 or "Nueva versión"
             )

             try:

                 toast(
                     title=f"{juego} actualizado",
                     body=f"Nueva versión disponible:\n{release_name}",
                
                 )

             except Exception as e:

                 print("Error toast:", e)

             saved_dates[juego] = latest_date

             self.config_data["release_dates"] = saved_dates

             self.save_config()



    def on_releases_loaded(self, cache):

         self.releases_cache = cache

         for juego, data in cache.items():

             self.check_new_releases(
                 juego,
                 data
             )

         self.releases_loaded = True

         self.load_versions()



    def start_update_timer(self):

          if hasattr(self, "update_timer"):
              self.update_timer.stop()

          self.update_timer = QTimer(self)

          self.update_timer.timeout.connect(
              self.background_update_check
          )

          interval = self.config_data.get(
              "update_check_interval",
              60
          )

          self.update_timer.start(
              interval * 60 * 1000
          )


    def background_update_check(self):

          print("Comprobando actualizaciones...")

          for juego, repo in REPOS.items():

              try:

                  r = requests.get(
                      f"https://api.github.com/repos/{repo}/releases?per_page=100",
                      timeout=15
                  )

                  data = r.json()

                  self.releases_cache[juego] = data

                  self.check_new_releases(
                      juego,
                      data
                  )

              except Exception as e:

                  print(
                      f"Error comprobando {juego}:",
                      e
                  )

    def save_update_settings(self):

          self.config_data[
              "update_check_interval"
          ] = self.interval_spin.value()

          self.save_config()

          self.start_update_timer()

          
    #------------------------------
    # Logic mods
    #------------------------------
    def create_mod_card(self, mod_name, mods_path):

          card = QFrame()

          card.setFixedSize(590, 82)

          card.setStyleSheet("""
              QFrame {
                  background:#202020;
                  border-radius:14px;
              }

              QFrame:hover {
                  background:#202020;
              }
          """)

          layout = QHBoxLayout(card)

          layout.setContentsMargins(
              16, 12, 16, 12
          )

          activo = not mod_name.endswith(".disabled")

          nombre_visible = mod_name

          if nombre_visible.endswith(".disabled"):
              nombre_visible = nombre_visible[:-9]

          nombre_visible = os.path.splitext(nombre_visible)[0]

          info = QVBoxLayout()

          title = QLabel(nombre_visible)

          title.setStyleSheet("""
              color:white;
              font-size:13px;
              font-weight:600;
          """)

          subtitle = QLabel(
              "Activo" if activo else "Desactivado"
          )

          subtitle.setStyleSheet("""
              color:#9a9a9a;
              font-size:11px;
          """)

          info.addWidget(title)
          info.addWidget(subtitle)

          layout.addLayout(info)

          layout.addStretch()

          toggle_btn = QPushButton()

          toggle_btn.setFixedSize(36, 36)

          if activo:

              toggle_btn.setText("💡")

              toggle_btn.setStyleSheet("""
                  QPushButton {
                      background:#00c853;
                      color:black;
                      border:none;
                      border-radius:10px;
                      font-weight:bold;
                  }

                  QPushButton:hover {
                      background:#19e06c;
                  }
                  QPushButton:focus {
                    outline:none;
                    border:none;
                  }
              """)

          else:

              toggle_btn.setText("💡")

              toggle_btn.setStyleSheet("""
                  QPushButton {
                      background:#3a3a3a;
                      color:white;
                      border:none;
                      border-radius:10px;
                      font-weight:bold;
                  }

                  QPushButton:hover {
                      background:#707070;
                  }
                  QPushButton:focus {
                    outline:none;
                    border:none;
                  }
              """)

          toggle_btn.clicked.connect(
              lambda _, n=mod_name:
              self.toggle_mod(mods_path, n)
          )

          layout.addWidget(toggle_btn)

          delete_btn = QPushButton("🗑")
          delete_btn.setFixedSize(36, 36)

          delete_btn.setStyleSheet("""
              QPushButton {
                  background:#3a3a3a;
                  color:white;
                  border:none;
                  border-radius:10px;
                  font-size:14px;
              }

              QPushButton:hover {
                  background:#c83c3c;
              }
              QPushButton:focus {
                    outline:none;
                    border:none;
              }
          """)

          delete_btn.clicked.connect(
              lambda _, n=mod_name:
              self.delete_mod(mods_path, n)
          )

          layout.addWidget(delete_btn)

          return card

    def toggle_mod(self, mods_path, mod_name):

          try:

              origen = os.path.join(
                  mods_path,
                  mod_name
              )

              if mod_name.endswith(".disabled"):

                  destino = os.path.join(
                      mods_path,
                      mod_name[:-9]
                  )

              else:

                  destino = os.path.join(
                      mods_path,
                      mod_name + ".disabled"
                  )

              os.rename(
                  origen,
                  destino
              )

              self.load_mods()

          except Exception as e:

              QMessageBox.warning(
                  self,
                  "Error",
                  f"No se pudo cambiar el estado del mod:\n\n{e}"
              )

              
    def load_mods(self):

         if not hasattr(self, "mods_layout"):
             return

         while self.mods_layout.count():

             item = self.mods_layout.takeAt(0)

             widget = item.widget()

             if widget:
                 widget.deleteLater()

         juego = JUEGOS[self.juego_activo]

         active = self.active_installations.get(juego)

         if not active:

             label = QLabel("No hay instalación activa")
             label.setStyleSheet("color:white;")

             self.mods_layout.addWidget(label)
             self.mods_layout.addStretch()

             return

         base_path = active.get("path")

         if not base_path:

             label = QLabel("No hay instalación activa")
             label.setStyleSheet("color:white;")

             self.mods_layout.addWidget(label)
             self.mods_layout.addStretch()

             return

         mods_path = os.path.join(
             base_path,
             "mods"
         )

         if not os.path.exists(mods_path):

             label = QLabel("La instalación no tiene carpeta mods")
             label.setStyleSheet("color:white;")

             self.mods_layout.addWidget(label)
             self.mods_layout.addStretch()

             return

         archivos = sorted(
             os.listdir(mods_path)
         )

         archivos = [
             a for a in archivos
             if os.path.isfile(os.path.join(mods_path, a))
         ]

         if not archivos:

             label = QLabel("No hay mods instalados")
             label.setStyleSheet("color:white;")

             self.mods_layout.addWidget(label)
             self.mods_layout.addStretch()

             return

         for archivo in archivos:

               card = self.create_mod_card(
                   archivo,
                   mods_path
               )

               self.mods_layout.addWidget(card)

         self.mods_layout.addStretch()




    def delete_mod(self, mods_path, mod_name):

        msgbox = QMessageBox(self)
        msgbox.setWindowFlag(Qt.FramelessWindowHint)

        msgbox.setText(
            f"¿Seguro que quieres borrar este mod?\n\n{mod_name}"
        )

        msgbox.setStandardButtons(
            QMessageBox.Yes | QMessageBox.No
        )

        msgbox.setDefaultButton(QMessageBox.No)

        msgbox.setStyleSheet("""
            QMessageBox {
                background:#232323;
                border-radius:14px;
                border:1px solid #000000;
            }

            QLabel {
                color:white;
                font-size:12px;
                font-weight:bold;
            }

            QPushButton {
                background:#3a3a3a;
                color:white;
                border:none;
                border-radius:8px;
                padding:8px 14px;
                min-width:70px;
            }

            QPushButton:hover {
                background:#c83c3c;
            }
            QPushButton:focus {
                    outline:none;
                    border:none;
            }
        """)

        if msgbox.exec() != QMessageBox.Yes:
            return

        try:
            os.remove(os.path.join(mods_path, mod_name))
            self.load_mods()

        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                f"No se pudo borrar el mod:\n\n{e}"
            )
    
    #------------------------------
    # Gamebanana page details logic
    #------------------------------

    def fix_description_colors(self, html):
        
        html = re.sub(
            r'color\s*:\s*[^;"\']+',
            'color:#FFD54F',
            html,
            flags=re.IGNORECASE
        )
        
        html = re.sub(
            r'(<font[^>]*?)\s+color\s*=\s*["\'][^"\']*["\']',
            r'\1 color="#FFD54F"',
            html,
            flags=re.IGNORECASE
        )

        html = re.sub(
            r'<a\b',
            '<a style="color:#FFD54F; text-decoration:none;"',
            html,
            flags=re.IGNORECASE
        )

        return html
    
    def abrir_detalles_mod(self, mod_id, mod_type):

         data = self.gamebanana_page.obtener_detalles_mod(
             mod_id,
             mod_type
         )

         if not data:
             return

         images, description, files = data

         # -------------------------
         # DESCRIPCIÓN
         # -------------------------
         description = self.fix_description_colors(description)

         self.mod_desc.setHtml(description)

         # -------------------------
         # ARCHIVOS
         # -------------------------

         while self.mod_files_layout.count():

            item = self.mod_files_layout.takeAt(0)

            widget = item.widget()

            if widget:
                widget.deleteLater()

         for name, url in files:

            card = self.create_mod_file_card(
                name,
                url
            )

            self.mod_files_layout.addWidget(
                card
            )

         # -------------------------
         # IMAGEN
         # -------------------------
         self.mod_images = images
         self.mod_image_index = 0

         for url in images:

              if url in self.mod_image_cache:
                  continue

              self.gamebanana_page.executor.submit(
                  self.preload_mod_image,
                  url
              )

         if self.mod_images:
             self.show_mod_image()


         self.stack.setCurrentWidget(
             self.mod_details_page
         )

    def preload_mod_image(self, url):

         if url in self.mod_image_cache:
             return

         try:

             r = requests.get(
                 url,
                 timeout=10
             )

             qimg = QImage.fromData(
                 r.content
             )

             if qimg.isNull():
                 return

             pix = QPixmap.fromImage(qimg).scaled(
                 520,
                 280,
                 Qt.KeepAspectRatioByExpanding,
                 Qt.SmoothTransformation
             )

             self.mod_image_cache[url] = pix

         except Exception as e:

             print(
                 "Error precargando:",
                 e
             )

    def show_mod_image(self):

         if not self.mod_images:
             return

         url = self.mod_images[
             self.mod_image_index
         ]

         if url in self.mod_image_cache:

             self.mod_image.setPixmap(
                 self.mod_image_cache[url]
             )

             return

         try:

             r = requests.get(
                 url,
                 timeout=10
             )

             qimg = QImage.fromData(
                 r.content
             )

             pix = QPixmap.fromImage(qimg).scaled(
                 520,
                 280,
                 Qt.KeepAspectRatioByExpanding,
                 Qt.SmoothTransformation
             )

             self.mod_image_cache[url] = pix

             self.mod_image.setPixmap(pix)

         except Exception as e:

             print("Error imagen:", e)

    def next_mod_image(self):

        if not self.mod_images:
            return

        self.mod_image_index += 1

        if self.mod_image_index >= len(self.mod_images):
            self.mod_image_index = 0

        self.show_mod_image()

    def prev_mod_image(self):

        if not self.mod_images:
            return

        self.mod_image_index -= 1

        if self.mod_image_index < 0:
            self.mod_image_index = len(self.mod_images) - 1

        self.show_mod_image()
        
    def download_mod_file(self, item):

         url = item.data(0, Qt.UserRole)

         name = item.text(0)

         path, _ = QFileDialog.getSaveFileName(
             self,
             "Guardar archivo",
             name
         )

         if not path:
             return

         r = requests.get(url, stream=True)

         with open(path, "wb") as f:

             for c in r.iter_content(8192):
                 f.write(c)



    def create_mod_file_card(self, name, url):
    
        card = QFrame()

        card.setStyleSheet("""
            QFrame {
                background:#202020;
                border-radius:12px;
            }
        """)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)

        # -------------------------
        # INFO
        # -------------------------

        info = QVBoxLayout()

        title = QLabel(name)

        title.setStyleSheet("""
            color:white;
            font-weight:bold;
            font-size:12px;
        """)

        status = QLabel("No instalado")

        status.setStyleSheet("""
            color:#9a9a9a;
            font-size:11px;
        """)

        info.addWidget(title)
        info.addWidget(status)

        layout.addLayout(info)

        layout.addStretch()

        # -------------------------
        # PROGRESS
        # -------------------------

        progress = QProgressBar()

        progress.setFixedWidth(90)
        progress.setFixedHeight(6)

        progress.setTextVisible(False)

        progress.setStyleSheet("""
            QProgressBar {
                background:#151515;
                border:none;
                border-radius:3px;
            }

            QProgressBar::chunk {
                background:#00c8ff;
                border-radius:3px;
            }
        """)

        progress.hide()

        layout.addWidget(progress)

        # -------------------------
        # DOWNLOAD
        # -------------------------

        btn = QPushButton("⭳")

        btn.setFixedSize(36, 36)

        btn.setStyleSheet("""
            QPushButton {
                background:#c83c3c;
                color:black;
                border:none;
                border-radius:10px;
                font-size:16px;
                font-weight:bold;
            }

            QPushButton:hover {
                background:#e04b4b;
            }
            QPushButton:focus {
                    outline:none;
                    border:none;
            }
        """)

        layout.addWidget(btn)

        btn.clicked.connect(
            lambda:
            self.download_mod_asset(
                name,
                url,
                progress,
                status,
                btn
            )
        )

        return card

    def download_mod_asset(
        self,
        name,
        url,
        progress,
        status,
        btn
    ):

        juego = JUEGOS[self.juego_activo]

        active = self.active_installations.get(juego)

        if not active:

            QMessageBox.warning(
                self,
                "Sin instalación",
                "No hay una instalación activa para este juego."
            )

            return

        base_path = active.get("path")

        if not base_path:

            QMessageBox.warning(
                self,
                "Ruta inválida",
                "La instalación activa no tiene una ruta válida."
            )

            return

        mods_path = os.path.join(
            base_path,
            "mods"
        )

        os.makedirs(
            mods_path,
            exist_ok=True
        )

        destination = os.path.join(
            mods_path,
            name
        )

        progress.setValue(0)
        progress.show()

        btn.setEnabled(False)

        status.setText("Preparando descarga...")

        thread = ModFileDownloadThread(
            url,
            destination
        )

        self.mod_downloads.append(thread)

        thread.progress.connect(
            progress.setValue
        )

        thread.status.connect(
            status.setText
        )

        def finished(path):
            
            if path.lower().endswith(".zip"):

                dialog = ZipSelectionDialog(path,self)

                OFFSET_X = 50    
                OFFSET_Y = 20   

                center_pos = (
                    self.frameGeometry().center()
                    - dialog.rect().center()
                )

                dialog.move(
                    center_pos.x() + OFFSET_X,
                    center_pos.y() + OFFSET_Y
                )

                if dialog.exec() != QDialog.Accepted:

                    os.remove(path)

                    progress.hide()

                    btn.setEnabled(True)

                    btn.setText("⭳")

                    return

                archivos = dialog.selected_files()

                with zipfile.ZipFile(path, "r") as z:

                    for nombre in archivos:

                        if nombre.endswith("/"):
                            continue

                        destino = os.path.join(
                            mods_path,
                            os.path.basename(nombre)
                        )

                        with z.open(nombre) as origen, open(destino, "wb") as salida:
                            shutil.copyfileobj(origen, salida)

                os.remove(path)
            
            status.setText("Instalado")

            progress.hide()

            btn.setText("✔")

            btn.setEnabled(False)

            btn.setStyleSheet("""
                QPushButton {
                    background:#00c853;
                    color:blank;
                    border:none;
                    border-radius:10px;
                    font-size:15px;
                    font-weight:bold;
                }

                QPushButton:hover {
                    background:#00c853;
                }
                QPushButton:focus {
                    outline:none;
                    border:none;
                }
            """)

            if thread in self.mod_downloads:
                self.mod_downloads.remove(thread)

            self.load_mods()

        def handle_status(msg):

            status.setText(msg)

            if msg.startswith("Error:"):

                progress.hide()

                btn.setEnabled(True)

                btn.setText("⭳")

                btn.setStyleSheet("""
                    QPushButton {
                        background:#c83c3c;
                        color:black;
                        border:none;
                        border-radius:10px;
                        font-size:16px;
                        font-weight:bold;
                    }

                    QPushButton:hover {
                        background:#e04b4b;
                    }
                    QPushButton:focus {
                        outline:none;
                        border:none;
                    }
                """)

                if thread in self.mod_downloads:
                    self.mod_downloads.remove(thread)

        thread.status.connect(
            handle_status
        )

        thread.finished.connect(
            finished
        )

        thread.start()
    
    #---------------------
    # JSON file logic
    #---------------------
    def load_config(self):

         default_data = {
             "active_installations": {
                 juego: None for juego in JUEGOS
             },
             "release_dates": {},
             "update_check_interval": 60
         }

         if not os.path.exists(CONFIG_FILE):

             self.config_data = default_data

             self.active_installations = (
                 self.config_data["active_installations"]
             )

             self.save_config()
             return

         try:

             with open(CONFIG_FILE, "r", encoding="utf-8") as f:

                 self.config_data = json.load(f)

             if "active_installations" not in self.config_data:
                 self.config_data["active_installations"] = {}

             if "release_dates" not in self.config_data:
                 self.config_data["release_dates"] = {}

             if "update_check_interval" not in self.config_data:
                 self.config_data["update_check_interval"] = 60

             
             for juego in JUEGOS:

                 if juego not in self.config_data["active_installations"]:

                     self.config_data["active_installations"][juego] = None

             self.active_installations = (
                 self.config_data["active_installations"]
             )

             self.save_config()

         except Exception as e:

             print("Error cargando config:", e)

             self.config_data = default_data

             self.active_installations = (
                 self.config_data["active_installations"]
             )

    def save_config(self):

         try:

             self.config_data["active_installations"] = (
                 self.active_installations
             )

             with open(CONFIG_FILE, "w", encoding="utf-8") as f:

                 json.dump(
                     self.config_data,
                     f,
                     indent=4,
                     ensure_ascii=False
                 )

         except Exception as e:

             print("Error guardando config:", e)

    #---------------------
    #
    #---------------------
    def showEvent(self, event):

         super().showEvent(event)

         self.update_background()


    def update_active_buttons(self):

         # Juegos
         for idx, btn in enumerate(self.game_buttons):

             btn.setProperty(
                 "active",
                 idx == self.juego_activo
             )

             btn.style().unpolish(btn)
             btn.style().polish(btn)

         # Tabs
         for idx, btn in enumerate(self.tab_buttons):

             btn.setProperty(
                 "active",
                 idx == self.tab_activa
             )

             btn.style().polish(btn)
             btn.update()

         
    def set_game(self, i):

        self.btn_config.setProperty("active", False)
        self.btn_config.style().unpolish(self.btn_config)
        self.btn_config.style().polish(self.btn_config)

        self.juego_activo = i
        juego = JUEGOS[i]
        self.set_tab(0)
        self.tab_activa = 0

        self.update_general_label()
        self.update_background()
        self.load_versions()
        self.load_mods()
        self.update_active_buttons()

        self.gamebanana_page.clear_cards()
        self.gamebanana_page.mods = []
        self.gamebanana_page.mods_cache.clear()
        self.gamebanana_page.img_cache.clear()
        self.gamebanana_page.search.clear()
        self.gamebanana_page.all_mods = []

    def set_tab(self, i):

        self.btn_config.setProperty("active", False)
        self.btn_config.style().unpolish(self.btn_config)
        self.btn_config.style().polish(self.btn_config)

        self.tab_activa = i 
        self.stack.setCurrentIndex(i)
        self.update_active_buttons()

        if TABS[i] == "GameBanana":
            juego = JUEGOS[self.juego_activo]
            self.gamebanana_page.load_game(juego)
     
    # -------------------------
    # DRAG WINDOW
    # -------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() <= 60:
                self._dragging = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = HM64Launcher()
    w.show()
    sys.exit(app.exec())
