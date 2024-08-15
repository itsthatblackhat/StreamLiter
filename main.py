import collections
import sys
import subprocess
import threading
import time
import os
import cv2
import numpy as np
import psutil
import requests
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QHBoxLayout, QListWidget, QLineEdit, QFormLayout, QStackedWidget
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
import configparser
import logging
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Full
import vlc

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration file
config_file = 'config.ini'

class StreamLiterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.frame_queue = Queue(maxsize=5)

        # Set window properties
        self.setWindowTitle('StreamLiter')
        self.setGeometry(100, 100, 1024, 768)

        # Load settings from config file
        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        # Initialize audio devices
        self.audio_devices = self.get_audio_devices()

        # Initialize VLC instance and media player
        self.initialize_vlc()

        # Initialize UI elements first, so they exist before applying settings
        self.quality_preset_input = QComboBox(self)

        # Initialize video resolution and other settings
        self.update_application_settings()

        # Create a main layout
        main_layout = QVBoxLayout()

        # Sidebar and stacked widget setup
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.addItem("Editor")
        self.sidebar.addItem("Overlays")
        self.sidebar.addItem("App Store")
        self.sidebar.addItem("Highlighter")
        self.sidebar.addItem("Settings")
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #2b2b2b;
                color: #ffffff;
                font: 16px;
            }
            QListWidget::item:selected {
                background-color: #444444;
                color: #ffffff;
            }
        """)
        self.stack = QStackedWidget()

        # Views
        self.editor_view = self.create_editor_view()
        self.stack.addWidget(self.editor_view)
        self.overlays_view = QLabel("Overlays View (Coming Soon)", self)
        self.stack.addWidget(self.overlays_view)
        self.appstore_view = QLabel("App Store View (Coming Soon)", self)
        self.stack.addWidget(self.appstore_view)
        self.highlighter_view = QLabel("Highlighter View (Coming Soon)", self)
        self.stack.addWidget(self.highlighter_view)
        self.settings_view = self.create_settings_view()
        self.stack.addWidget(self.settings_view)

        # Layout
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.sidebar)
        h_layout.addWidget(self.stack)
        main_layout.addLayout(h_layout)

        # Status Labels
        self.local_rtmp_status_label = QLabel("Local RTMP Server: Not Running", self)
        self.local_rtmp_status_label.setStyleSheet("font: 16px; color: red;")
        self.connection_status_label = QLabel("Connection Status: Not Connected", self)
        self.connection_status_label.setStyleSheet("font: 16px; color: red;")
        self.streaming_status_label = QLabel("Streaming Status: Not Streaming", self)
        self.streaming_status_label.setStyleSheet("font: 16px; color: red;")
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.local_rtmp_status_label)
        status_layout.addWidget(self.connection_status_label)
        status_layout.addWidget(self.streaming_status_label)
        main_layout.addLayout(status_layout)

        # RTMP Server Control Buttons
        self.start_rtmp_button = QPushButton("Start RTMP Server", self)
        self.start_rtmp_button.clicked.connect(self.start_local_rtmp_server)
        self.stop_rtmp_button = QPushButton("Stop RTMP Server", self)
        self.stop_rtmp_button.clicked.connect(self.stop_local_rtmp_server)
        rtmp_button_layout = QHBoxLayout()
        rtmp_button_layout.addWidget(self.start_rtmp_button)
        rtmp_button_layout.addWidget(self.stop_rtmp_button)
        main_layout.addLayout(rtmp_button_layout)

        # Apply Layout
        self.setLayout(main_layout)

        # Start FFmpeg capture in a separate thread
        self.capture_thread = threading.Thread(target=self.ffmpeg_capture)
        self.capture_thread.daemon = True
        self.capture_thread.start()

        # Timer for updating the preview
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_preview)

        # Connect sidebar selection to the stacked widget
        self.sidebar.currentRowChanged.connect(self.switch_view)
        self.sidebar.setCurrentRow(0)

        # Check RTMP Server Status
        self.check_rtmp_server_status()

    def initialize_vlc(self):
        try:
            self.vlc_instance = vlc.Instance("--network-caching=50")
            self.vlc_player = self.vlc_instance.media_player_new()
            logger.info("VLC initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize VLC: {e}")

    def start_preview(self):
        try:
            local_stream_url = f'rtmp://{self.local_rtmp_server}:{self.local_rtmp_port}/live/stream'
            logger.info(f"Loading local preview stream from URL: {local_stream_url}")
            media = self.vlc_instance.media_new(local_stream_url)
            self.vlc_player.set_media(media)

            # Set the player to render video in the correct widget
            if sys.platform == "linux":  # for Linux using the X Server
                self.vlc_player.set_xwindow(int(self.video_widget.winId()))
            elif sys.platform == "win32":  # for Windows
                self.vlc_player.set_hwnd(int(self.video_widget.winId()))
            elif sys.platform == "darwin":  # for MacOS
                self.vlc_player.set_nsobject(int(self.video_widget.winId()))

            if self.vlc_player.play() == -1:
                raise Exception("VLC failed to play the stream")

            # Use a loop to check VLC status for a more robust status update
            self.poll_vlc_status()

        except Exception as e:
            self.connection_status_label.setText("Connection Status: Failed to Load Stream")
            self.connection_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to load preview: {e}")

    def check_vlc_status(self):
        max_attempts = 10
        attempts = 0

        while attempts < max_attempts:
            time.sleep(0.5)  # Wait for half a second before each check
            if self.vlc_player.is_playing():
                logger.info("Media player started successfully.")
                self.connection_status_label.setText("Connection Status: Connected")
                self.connection_status_label.setStyleSheet("font: 16px; color: green;")
                return
            attempts += 1

        logger.warning("Media player failed to start.")
        self.connection_status_label.setText("Connection Status: Failed to Start")
        self.connection_status_label.setStyleSheet("font: 16px; color: red;")

    def get_audio_devices(self):
        # Using a PowerShell script to get audio devices
        devices = {"Playback": ["None"], "Recording": ["None"]}
        try:
            process = subprocess.Popen(
                ["powershell", "-Command", "Get-AudioDevice -List"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            output, error = process.communicate()
            if process.returncode == 0:
                for line in output.splitlines():
                    if "Playback" in line:
                        devices["Playback"].append(line.split(":")[-1].strip())
                    elif "Recording" in line:
                        devices["Recording"].append(line.split(":")[-1].strip())
            else:
                logger.error(f"Error getting audio devices: {error}")
        except Exception as e:
            logger.error(f"Error getting audio devices: {e}")
        return devices

    def update_application_settings(self):
        self.rtmp_url = self.config.get('Streaming', 'rtmp_url', fallback='rtmp://localhost/live')
        self.stream_key = self.config.get('Streaming', 'stream_key', fallback='your_stream_key')
        self.video_res = self.config.get('Video', 'resolution', fallback='1920x1080')
        self.local_rtmp_server = self.config.get('RTMP', 'server', fallback='localhost')
        self.local_rtmp_port = self.config.get('RTMP', 'port', fallback='1935')
        self.preset = self.config.get('Streaming', 'preset', fallback='veryfast')
        self.crf = self.config.get('Streaming', 'crf', fallback='23')
        self.maxrate = self.config.get('Streaming', 'maxrate', fallback='8M')
        self.bufsize = self.config.get('Streaming', 'bufsize', fallback='10M')
        self.quality_preset = self.config.get('Streaming', 'quality_preset', fallback='Medium')
        self.gop_size = self.config.get('FFmpeg', 'gop_size', fallback='30')
        self.tune = self.config.get('FFmpeg', 'tune', fallback='zerolatency')
        self.fflags = self.config.get('FFmpeg', 'fflags', fallback='nobuffer')
        self.flags = self.config.get('FFmpeg', 'flags', fallback='low_delay')
        self.probesize = self.config.get('FFmpeg', 'probesize', fallback='32')
        self.apply_quality_preset()

    def apply_quality_preset(self):
        preset = self.quality_preset_input.currentText()

        if preset == "High":
            self.preset_input.setCurrentText("slow")
            self.crf_input.setText("18")
            self.maxrate_input.setText("10M")
            self.bufsize_input.setText("20M")
        elif preset == "Medium":
            self.preset_input.setCurrentText("veryfast")
            self.crf_input.setText("23")
            self.maxrate_input.setText("8M")
            self.bufsize_input.setText("10M")
        elif preset == "Low":
            self.preset_input.setCurrentText("ultrafast")
            self.crf_input.setText("28")
            self.maxrate_input.setText("4M")
            self.bufsize_input.setText("8M")

    def switch_view(self, index):
        self.stack.setCurrentIndex(index)

    def create_editor_view(self):
        editor_layout = QVBoxLayout()

        # Create a combo box for source selection
        self.source_combo = QComboBox(self)
        self.source_combo.addItems(["Screen Capture", "Webcam", "Window Capture"])
        editor_layout.addWidget(self.source_combo)

        # Create the video widget for stream preview
        self.video_widget = QVideoWidget(self)
        self.video_widget.setFixedSize(800, 450)  # Fixed size
        self.video_widget.setStyleSheet("background-color: #2b2b2b;")
        editor_layout.addWidget(self.video_widget)

        # Create the switch source and go live buttons
        button_layout = QHBoxLayout()
        self.switch_button = QPushButton("Switch Source")
        self.switch_button.setFixedHeight(50)
        self.switch_button.clicked.connect(self.switch_source)
        button_layout.addWidget(self.switch_button)

        self.go_live_button = QPushButton("Go Live")
        self.go_live_button.setFixedHeight(50)
        self.go_live_button.clicked.connect(self.start_streaming_thread)
        button_layout.addWidget(self.go_live_button)

        self.test_stream_button = QPushButton("Test Stream")
        self.test_stream_button.setFixedHeight(50)
        self.test_stream_button.clicked.connect(self.start_test_stream)
        button_layout.addWidget(self.test_stream_button)

        editor_layout.addLayout(button_layout)

        editor_widget = QWidget()
        editor_widget.setLayout(editor_layout)

        return editor_widget

    def terminate_ffmpeg_process(self):
        """Terminate any running FFmpeg process to avoid conflicts."""
        for proc in psutil.process_iter(['pid', 'name']):
            if 'ffmpeg' in proc.info['name']:
                logger.info(f"Terminating existing FFmpeg process with PID: {proc.info['pid']}")
                proc.kill()

    def ffmpeg_capture(self):
        # Ensure no other FFmpeg process is running
        self.terminate_ffmpeg_process()

        capture_command = [
            'C:\\ProgrammingProjects\\StreamLiter\\ffmpeg\\bin\\ffmpeg.exe',
            '-video_size', self.video_res,
            '-framerate', '20',
            '-f', 'gdigrab',
            '-i', 'desktop',
            '-pix_fmt', 'yuv420p',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',  # Fastest encoding
            '-tune', 'zerolatency',  # Tuning for low latency
            '-g', '15',  # Smaller GOP for quicker keyframes
            '-fflags', 'nobuffer',
            '-flags', 'low_delay',
            '-probesize', '32',
            '-analyzeduration', '0',
            '-f', 'flv',
            f'rtmp://{self.local_rtmp_server}:{self.local_rtmp_port}/live/stream'
        ]

        logger.info(f"Starting FFmpeg with command: {' '.join(capture_command)}")

        try:
            self.ffmpeg_process = subprocess.Popen(
                capture_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10 ** 8
            )

            while True:
                if self.ffmpeg_process.poll() is not None:
                    logger.error("FFmpeg process has terminated unexpectedly.")
                    stderr_output = self.ffmpeg_process.stderr.read().decode('utf-8')
                    if 'Already publishing' in stderr_output:
                        logger.error("RTMP server is already publishing. Terminating FFmpeg process.")
                    else:
                        logger.error(f"FFmpeg stderr: {stderr_output}")
                    self.connection_status_label.setText("Connection Status: FFmpeg Error")
                    self.connection_status_label.setStyleSheet("font: 16px; color: red;")
                    break

                raw_frame = self.ffmpeg_process.stdout.read(1280 * 720 * 3)
                if not raw_frame:
                    logger.error("No data read from FFmpeg stdout. FFmpeg may have exited.")
                    stderr_output = self.ffmpeg_process.stderr.read().decode('utf-8')
                    logger.error(f"FFmpeg stderr: {stderr_output}")
                    self.connection_status_label.setText("Connection Status: FFmpeg Error")
                    self.connection_status_label.setStyleSheet("font: 16px; color: red;")
                    break

                try:
                    self.frame_queue.put_nowait(raw_frame)
                except Full:
                    logger.warning("Frame queue is full. Dropping frame.")

                time.sleep(0.005)

        except Exception as e:
            logger.error(f"Exception in ffmpeg_capture: {str(e)}")
            self.connection_status_label.setText("Connection Status: FFmpeg Error")
            self.connection_status_label.setStyleSheet("font: 16px; color: red;")

    def update_preview(self):
        if not self.frame_queue.empty():
            raw_frame = self.frame_queue.get()
            frame = np.frombuffer(raw_frame, np.uint8).reshape((720, 1280, 3))
            self.executor.submit(self.process_frame, frame)

    def process_frame(self, frame):
        try:
            if frame is not None:
                # Ensure proper scaling to match the preview label size
                height, width, _ = frame.shape
                aspect_ratio = width / height

                scaled_height = self.video_widget.height()
                scaled_width = int(scaled_height * aspect_ratio)

                if scaled_width > self.video_widget.width():
                    scaled_width = self.video_widget.width()
                    scaled_height = int(scaled_width / aspect_ratio)

                scaled_frame = cv2.resize(frame, (scaled_width, scaled_height))
                scaled_frame = cv2.cvtColor(scaled_frame, cv2.COLOR_BGR2RGB)

                img = QImage(scaled_frame.data, scaled_frame.shape[1], scaled_frame.shape[0], scaled_frame.strides[0],
                             QImage.Format_RGB888)
                self.video_widget.setPixmap(QPixmap.fromImage(img))
            else:
                logger.warning("No frame available for display.")
        except Exception as e:
            logger.error(f"Error in display_frame: {str(e)}")

    def create_settings_view(self):
        settings_layout = QVBoxLayout()

        # Streaming Settings Group
        streaming_group = QVBoxLayout()
        streaming_group_box = QWidget()
        streaming_group_box.setLayout(streaming_group)
        streaming_group_box.setStyleSheet("background-color: #2b2b2b; color: #ffffff; border: 1px solid #444444;")

        streaming_layout = QFormLayout()

        # Create settings fields
        self.rtmp_url_input = QLineEdit(self)
        self.rtmp_url_input.setText(self.config.get('Streaming', 'rtmp_url', fallback='rtmp://localhost/live'))
        streaming_layout.addRow('Stream RTMP URL:', self.rtmp_url_input)

        self.stream_key_input = QLineEdit(self)
        self.stream_key_input.setText(self.config.get('Streaming', 'stream_key', fallback='your_stream_key'))
        streaming_layout.addRow('Stream RTMP Key:', self.stream_key_input)

        self.video_res_input = QComboBox(self)
        self.video_res_input.addItems(["1920x1080", "1280x720", "640x480"])
        self.video_res_input.setCurrentText(self.config.get('Video', 'resolution', fallback='1920x1080'))
        streaming_layout.addRow('Streaming Resolution:', self.video_res_input)

        self.audio_human_input_device = QComboBox(self)
        self.audio_human_input_device.addItems(self.audio_devices["Recording"])
        streaming_layout.addRow('Human Audio Input Device:', self.audio_human_input_device)

        self.system_audio_input_device = QComboBox(self)
        self.system_audio_input_device.addItems(self.audio_devices["Playback"])
        streaming_layout.addRow('System Audio Input Device:', self.system_audio_input_device)

        self.local_rtmp_server_input = QLineEdit(self)
        self.local_rtmp_server_input.setText(self.config.get('RTMP', 'server', fallback='localhost'))
        streaming_layout.addRow('Local RTMP Server:', self.local_rtmp_server_input)

        self.local_rtmp_port_input = QLineEdit(self)
        self.local_rtmp_port_input.setText(self.config.get('RTMP', 'port', fallback='1935'))
        streaming_layout.addRow('Local RTMP Port:', self.local_rtmp_port_input)

        streaming_group.addLayout(streaming_layout)

        # FFmpeg Settings Group
        ffmpeg_group = QVBoxLayout()
        ffmpeg_group_box = QWidget()
        ffmpeg_group_box.setLayout(ffmpeg_group)
        ffmpeg_group_box.setStyleSheet("background-color: #2b2b2b; color: #ffffff; border: 1px solid #444444;")

        ffmpeg_layout = QFormLayout()

        # Add Quality Preset Selection
        self.quality_preset_input = QComboBox(self)
        self.quality_preset_input.addItems(["High", "Medium", "Low"])
        self.quality_preset_input.setCurrentText(self.config.get('Streaming', 'quality_preset', fallback='Medium'))
        self.quality_preset_input.currentIndexChanged.connect(self.apply_quality_preset)
        ffmpeg_layout.addRow('Quality Preset:', self.quality_preset_input)

        # Streaming Video Options
        self.preset_input = QComboBox(self)
        self.preset_input.addItems(
            ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.preset_input.setCurrentText(self.config.get('Streaming', 'preset', fallback='veryfast'))
        ffmpeg_layout.addRow('FFmpeg Preset:', self.preset_input)

        self.crf_input = QLineEdit(self)
        self.crf_input.setText(self.config.get('Streaming', 'crf', fallback='23'))
        ffmpeg_layout.addRow('Constant Rate Factor (CRF):', self.crf_input)

        self.maxrate_input = QLineEdit(self)
        self.maxrate_input.setText(self.config.get('Streaming', 'maxrate', fallback='8M'))
        ffmpeg_layout.addRow('Max Bitrate (e.g., 8M):', self.maxrate_input)

        self.bufsize_input = QLineEdit(self)
        self.bufsize_input.setText(self.config.get('Streaming', 'bufsize', fallback='10M'))
        ffmpeg_layout.addRow('Buffer Size (e.g., 10M):', self.bufsize_input)

        self.gop_size_input = QLineEdit(self)
        self.gop_size_input.setText(self.config.get('FFmpeg', 'gop_size', fallback='30'))
        ffmpeg_layout.addRow('GOP Size:', self.gop_size_input)

        self.tune_input = QComboBox(self)
        self.tune_input.addItems(["zerolatency", "film", "animation", "grain"])
        self.tune_input.setCurrentText(self.config.get('FFmpeg', 'tune', fallback='zerolatency'))
        ffmpeg_layout.addRow('Tune:', self.tune_input)

        self.fflags_input = QLineEdit(self)
        self.fflags_input.setText(self.config.get('FFmpeg', 'fflags', fallback='nobuffer'))
        ffmpeg_layout.addRow('FFlags:', self.fflags_input)

        self.flags_input = QLineEdit(self)
        self.flags_input.setText(self.config.get('FFmpeg', 'flags', fallback='low_delay'))
        ffmpeg_layout.addRow('Flags:', self.flags_input)

        self.probesize_input = QLineEdit(self)
        self.probesize_input.setText(self.config.get('FFmpeg', 'probesize', fallback='32'))
        ffmpeg_layout.addRow('Probesize:', self.probesize_input)

        ffmpeg_group.addLayout(ffmpeg_layout)

        # Add the groups to the main settings layout
        settings_layout.addWidget(streaming_group_box)
        settings_layout.addWidget(ffmpeg_group_box)

        save_button = QPushButton("Save Settings", self)
        save_button.clicked.connect(self.save_settings)
        settings_layout.addWidget(save_button)

        settings_widget = QWidget()
        settings_widget.setLayout(settings_layout)

        return settings_widget

    def save_settings(self):
        self.config['Streaming'] = {
            'rtmp_url': self.rtmp_url_input.text(),
            'stream_key': self.stream_key_input.text(),
            'quality_preset': self.quality_preset_input.currentText(),
            'preset': self.preset_input.currentText(),
            'crf': self.crf_input.text(),
            'maxrate': self.maxrate_input.text(),
            'bufsize': self.bufsize_input.text(),
        }
        self.config['Video'] = {
            'resolution': self.video_res_input.currentText()
        }
        self.config['Audio'] = {
            'human_input_device': self.audio_human_input_device.currentText(),
            'system_audio_input_device': self.system_audio_input_device.currentText()
        }
        self.config['RTMP'] = {
            'server': self.local_rtmp_server_input.text(),
            'port': self.local_rtmp_port_input.text()
        }
        self.config['FFmpeg'] = {
            'gop_size': self.gop_size_input.text(),
            'tune': self.tune_input.currentText(),
            'fflags': self.fflags_input.text(),
            'flags': self.flags_input.text(),
            'probesize': self.probesize_input.text()
        }
        with open(config_file, 'w') as configfile:
            self.config.write(configfile)
        logger.info("Settings saved.")

        # Update the application state to use the new settings
        self.update_application_settings()

    def switch_source(self):
        source = self.source_combo.currentText()
        logger.info(f"Switching source to: {source}")

        # Terminate any existing FFmpeg process to avoid RTMP conflicts
        self.terminate_ffmpeg_process()

        self.connection_status_label.setText("Connection Status: Starting Capture...")
        self.connection_status_label.setStyleSheet("font: 16px; color: orange;")

        # Give a short delay before starting the actual capture
        QTimer.singleShot(1000, self.start_screen_capture)

    def is_stream_active(self):
        """Check if the RTMP stream is already active."""
        try:
            response = requests.get(f"http://127.0.0.1:8080/stat")
            if response.status_code == 200:
                if f'<name>{self.stream_key}</name>' in response.text:
                    return True
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check RTMP stream status: {e}")
            return False

    def start_screen_capture(self):
        # Ensure the RTMP server is running
        if not self.is_rtmp_server_running():
            logger.error("RTMP server is not running. Cannot start screen capture.")
            self.connection_status_label.setText("Connection Status: RTMP Server Not Running")
            self.connection_status_label.setStyleSheet("font: 16px; color: red;")
            return

        # Check if a stream is already active on the RTMP server
        if self.is_stream_active():
            logger.info("Stream is already active, not starting a new capture process.")
            self.connection_status_label.setText("Connection Status: Already Streaming")
            self.connection_status_label.setStyleSheet("font: 16px; color: green;")
            return

        # Terminate any existing FFmpeg process to avoid RTMP conflicts
        self.terminate_ffmpeg_process()

        # Add a short delay to ensure resources are released
        time.sleep(2)

        # Command for capturing the screen and streaming to RTMP
        capture_command = [
            'C:\\ProgrammingProjects\\StreamLiter\\ffmpeg\\bin\\ffmpeg.exe',
            '-video_size', self.video_res,
            '-framerate', '30',
            '-f', 'gdigrab',
            '-i', 'desktop',
            '-pix_fmt', 'yuv420p',
            '-c:v', 'libx264',
            '-preset', self.preset,
            '-tune', self.tune,
            '-g', self.gop_size,
            '-fflags', self.fflags,
            '-flags', self.flags,
            '-f', 'flv',
            f'rtmp://{self.local_rtmp_server}:{self.local_rtmp_port}/live/stream'  # Output to local RTMP server
        ]

        try:
            logger.info(f"Starting screen capture command: {' '.join(capture_command)}")
            self.connection_status_label.setText("Connection Status: Capturing...")
            self.connection_status_label.setStyleSheet("font: 16px; color: orange;")

            self.ffmpeg_process = subprocess.Popen(
                capture_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Start checking the output stream and display it after a delay
            QTimer.singleShot(3000, self.start_preview)

        except Exception as e:
            self.connection_status_label.setText("Connection Status: Error Occurred")
            self.connection_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to start screen capture: {e}")

    def is_rtmp_server_running(self):
        """Check if the RTMP server is running."""
        try:
            response = requests.get("http://127.0.0.1:8080")
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def start_streaming_thread(self):
        # Run the streaming in a separate thread
        streaming_thread = threading.Thread(target=self.start_streaming)
        streaming_thread.start()

    def start_streaming(self):
        try:
            self.streaming_status_label.setText("Streaming Status: Streaming...")
            self.streaming_status_label.setStyleSheet("font: 16px; color: green;")

            # Stream locally to RTMP server
            stream_command = [
                'C:\\ProgrammingProjects\\StreamLiter\\ffmpeg\\bin\\ffmpeg.exe',
                '-video_size', f'{self.video_res}',
                '-framerate', '30',
                '-f', 'gdigrab',
                '-i', 'desktop',
                '-pix_fmt', 'yuv420p',
                '-c:v', 'libx264',
                '-preset', self.preset,
                '-tune', self.tune,
                '-g', self.gop_size,
                '-fflags', self.fflags,
                '-flags', self.flags,
                '-probesize', self.probesize,
                '-f', 'flv',
                'rtmp://localhost/live/stream'  # Local RTMP server
            ]

            logger.info(f"Starting FFmpeg with command: {' '.join(stream_command)}")
            self.streaming_process = subprocess.Popen(stream_command)

        except Exception as e:
            self.streaming_status_label.setText("Streaming Status: Error")
            self.streaming_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to start streaming: {e}")

    def start_local_rtmp_server(self):
        try:
            # Ensure required directories exist
            nginx_logs_dir = 'C:\\ProgrammingProjects\\StreamLiter\\nginx\\logs'
            nginx_temp_dir = 'C:\\ProgrammingProjects\\StreamLiter\\nginx\\temp'
            os.makedirs(nginx_logs_dir, exist_ok=True)
            os.makedirs(os.path.join(nginx_temp_dir, 'hls'), exist_ok=True)
            os.makedirs(os.path.join(nginx_temp_dir, 'client_body_temp'), exist_ok=True)

            # Start the NGINX server with correct working directory
            nginx_path = 'C:\\ProgrammingProjects\\StreamLiter\\nginx\\nginx.exe'
            nginx_dir = 'C:\\ProgrammingProjects\\StreamLiter\\nginx'
            server_command = [nginx_path]

            logger.info(f"Starting local RTMP server with command: {' '.join(server_command)}")
            self.local_rtmp_status_label.setText("Local RTMP Server: Starting...")
            self.local_rtmp_status_label.setStyleSheet("font: 16px; color: orange;")

            # Start the server with the working directory set to NGINX directory
            self.rtmp_server_process = subprocess.Popen(server_command, cwd=nginx_dir)

            # Wait a few seconds to allow the server to start
            time.sleep(3)

            # Check if the server is running
            self.check_rtmp_server_status()

        except Exception as e:
            self.local_rtmp_status_label.setText("Local RTMP Server: Not Running")
            self.local_rtmp_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to start RTMP server: {e}")

    def stop_local_rtmp_server(self):
        try:
            logger.info("Stopping local RTMP server...")

            # Look for the nginx process and terminate it
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] == 'nginx.exe':
                    proc.kill()
                    logger.info(f"Terminated nginx process with PID: {proc.info['pid']}")

            # Wait a few seconds to ensure the server stops
            time.sleep(3)

            # Check if the server is stopped
            self.check_rtmp_server_status()

        except Exception as e:
            self.local_rtmp_status_label.setText("Local RTMP Server: Error Stopping")
            self.local_rtmp_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to stop RTMP server: {e}")

    def check_rtmp_server_status(self):
        try:
            response = requests.get("http://127.0.0.1:8080")
            if response.status_code == 200:
                self.local_rtmp_status_label.setText("Local RTMP Server: Running")
                self.local_rtmp_status_label.setStyleSheet("font: 16px; color: green;")
                logger.info("RTMP server is running.")
            else:
                self.local_rtmp_status_label.setText("Local RTMP Server: Not Running")
                self.local_rtmp_status_label.setStyleSheet("font: 16px; color: red;")
                logger.info("RTMP server is not running.")
        except requests.exceptions.RequestException:
            self.local_rtmp_status_label.setText("Local RTMP Server: Not Running")
            self.local_rtmp_status_label.setStyleSheet("font: 16px; color: red;")
            logger.info("RTMP server is not running.")

    def start_test_stream(self):
        try:
            # Check if the RTMP server is running
            logger.info("Checking RTMP server status...")
            self.check_rtmp_server_status()

            if self.local_rtmp_status_label.text() != "Local RTMP Server: Running":
                logger.info("RTMP server not running. Attempting to start it...")

                # Stop and restart the RTMP server with a delay
                self.stop_local_rtmp_server()
                time.sleep(2)  # Wait for 2 seconds
                self.start_local_rtmp_server()
                time.sleep(2)  # Wait for another 2 seconds to ensure server is ready

                # Re-check the status
                self.check_rtmp_server_status()
                if self.local_rtmp_status_label.text() != "Local RTMP Server: Running":
                    self.streaming_status_label.setText("Streaming Status: Error - RTMP Server Not Running")
                    self.streaming_status_label.setStyleSheet("font: 16px; color: red;")
                    logger.error("Failed to start RTMP server.")
                    return

            # If RTMP server is running, start streaming
            logger.info("Starting test stream...")
            rtmp_url = f"rtmp://127.0.0.1:1936/live/stream"
            self.rtmp_url_input.setText(rtmp_url)
            self.start_streaming_thread()

        except Exception as e:
            self.streaming_status_label.setText("Streaming Status: Error")
            self.streaming_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to start test stream: {e}")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = StreamLiterApp()
    window.show()
    sys.exit(app.exec_())
