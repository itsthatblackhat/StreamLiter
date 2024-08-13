import sys
import subprocess
import ctypes
import numpy as np
import cv2
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QDialog
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer
import configparser

# Read settings from config file
config = configparser.ConfigParser()
config.read('config.ini')

# Capture settings from config or use defaults
CAPTURE_WIDTH = int(config['Capture'].get('width', 800))
CAPTURE_HEIGHT = int(config['Capture'].get('height', 600))
FPS = int(config['Capture'].get('fps', 30))

# FFmpeg settings from config or use defaults
FFMPEG_PATH = config['FFmpeg'].get('path', 'ffmpeg')
MAXRATE = config['FFmpeg'].get('maxrate', '9000k')
BUFSIZE = config['FFmpeg'].get('bufsize', '18000k')
GOP = config['FFmpeg'].get('g', '50')
AUDIO_BITRATE = config['FFmpeg'].get('audio_bitrate', '128k')
AUDIO_SAMPLERATE = config['FFmpeg'].get('audio_samplerate', '44100')
AUDIO_CHANNELS = int(config['FFmpeg'].get('audio_channels', 2))

# Streaming settings from config or use defaults
RTMP_URL = config['Streaming'].get('rtmp_url', 'rtmp://ca.pscp.tv:80/x')
STREAM_KEY = config['Streaming'].get('stream_key', 'a89m7cp5hica')

# Settings dialog for screen and audio selection
class SettingsDialog(QDialog):
    def __init__(self, available_screens, available_audio_devices, parent=None):
        super(SettingsDialog, self).__init__(parent)
        self.setWindowTitle('Settings')
        self.setGeometry(200, 200, 300, 200)

        layout = QVBoxLayout()

        # Screen selection
        self.screen_combo = QComboBox(self)
        self.screen_combo.addItems(available_screens)
        layout.addWidget(self.screen_combo)

        # Audio device selection
        self.audio_combo = QComboBox(self)
        self.audio_combo.addItems(available_audio_devices)
        layout.addWidget(self.audio_combo)

        self.setLayout(layout)

    def get_selected_screen(self):
        return self.screen_combo.currentText()

    def get_selected_audio_device(self):
        return self.audio_combo.currentText()

# Main application window
class StreamLiterApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('StreamLiter')
        self.setGeometry(100, 100, 800, 600)

        self.layout = QVBoxLayout()

        # Label to display the screen capture
        self.image_label = QLabel(self)
        self.layout.addWidget(self.image_label)

        # Button to start and stop the preview
        self.toggle_button = QPushButton('Toggle Preview', self)
        self.toggle_button.clicked.connect(self.toggle_preview)
        self.layout.addWidget(self.toggle_button)

        # Button to open settings
        self.settings_button = QPushButton('Settings', self)
        self.settings_button.clicked.connect(self.open_settings)
        self.layout.addWidget(self.settings_button)

        self.setLayout(self.layout)

        # Timer to update the screen capture
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_image)
        self.preview_active = False

        # Capture and Streaming variables
        self.selected_screen = None
        self.selected_audio_device = None

        # Launch the settings dialog on startup
        self.open_settings()

    def open_settings(self):
        available_screens = [f"Screen {i+1}" for i in range(2)]  # Replace with actual screen detection logic
        available_audio_devices = [
            "Stereo Mix (Realtek High Definition Audio)",
            "Speakers (Realtek High Definition Audio)"
        ]  # Replace with actual audio detection logic
        dialog = SettingsDialog(available_screens, available_audio_devices, self)
        if dialog.exec_():
            self.selected_screen = dialog.get_selected_screen()
            self.selected_audio_device = dialog.get_selected_audio_device()

    def toggle_preview(self):
        if self.preview_active:
            self.timer.stop()
            self.preview_active = False
            self.toggle_button.setText('Start Preview')
        else:
            self.timer.start(1000 // FPS)  # FPS from config
            self.preview_active = True
            self.toggle_button.setText('Stop Preview')

    def update_image(self):
        img = capture_screen(CAPTURE_WIDTH, CAPTURE_HEIGHT)
        img = cv2.resize(img, (self.width(), self.height()))
        height, width, channel = img.shape
        bytes_per_line = 3 * width
        qimg = QImage(img.data, width, height, bytes_per_line, QImage.Format_RGB888)
        self.image_label.setPixmap(QPixmap.fromImage(qimg))

def capture_screen(width, height):
    hwin = ctypes.windll.user32.GetDesktopWindow()
    hwindc = ctypes.windll.user32.GetWindowDC(hwin)
    srcdc = ctypes.windll.gdi32.CreateCompatibleDC(hwindc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hwindc, width, height)
    ctypes.windll.gdi32.SelectObject(srcdc, bmp)
    ctypes.windll.gdi32.BitBlt(srcdc, 0, 0, width, height, hwindc, 0, 0, 0x00CC0020)
    bmpinfo = ctypes.windll.gdi32.GetObject(bmp)
    bmpstr = ctypes.create_string_buffer(bmpinfo.bmWidth * bmpinfo.bmHeight * 4)
    ctypes.windll.gdi32.GetBitmapBits(bmp, len(bmpstr), bmpstr)
    ctypes.windll.gdi32.DeleteObject(bmp)
    img = np.frombuffer(bmpstr, dtype='uint8')
    img.shape = (height, width, 4)
    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img

def start_streaming(selected_screen, selected_audio_device):
    ffmpeg_command = [
        FFMPEG_PATH,
        '-f', 'dshow',
        '-i', f'audio={selected_audio_device}',  # Using selected audio device
        '-f', 'gdigrab',
        '-framerate', str(FPS),
        '-i', 'desktop',
        '-s', f'{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}',
        '-vcodec', 'libx264',
        '-preset', 'ultrafast',
        '-maxrate', MAXRATE,
        '-bufsize', BUFSIZE,
        '-g', GOP,
        '-acodec', 'aac',
        '-b:a', AUDIO_BITRATE,
        '-ar', AUDIO_SAMPLERATE,
        '-ac', str(AUDIO_CHANNELS),
        '-f', 'flv',
        f'{RTMP_URL}/{STREAM_KEY}'
    ]
    subprocess.run(ffmpeg_command)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = StreamLiterApp()
    window.show()
    sys.exit(app.exec_())
