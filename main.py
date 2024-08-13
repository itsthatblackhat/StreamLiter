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
from PyQt5.QtCore import QTimer, Qt
import configparser
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration file
config_file = 'config.ini'


class StreamLiterApp(QWidget):
    def __init__(self):
        super().__init__()

        # Set window properties
        self.setWindowTitle('StreamLiter')
        self.setGeometry(100, 100, 1024, 768)

        # Load settings from config file
        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        # Initialize audio devices
        self.audio_devices = self.get_audio_devices()

        # Create a main layout
        main_layout = QVBoxLayout()

        # Create a list widget for the sidebar
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.addItem("Editor")
        self.sidebar.addItem("Overlays")
        self.sidebar.addItem("App Store")
        self.sidebar.addItem("Highlighter")
        self.sidebar.addItem("Settings")

        # Set a dark theme for the sidebar
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

        # Create a stacked widget to switch between different views
        self.stack = QStackedWidget()

        # Editor View
        self.editor_view = self.create_editor_view()
        self.stack.addWidget(self.editor_view)

        # Overlays View (placeholder)
        self.overlays_view = QLabel("Overlays View (Coming Soon)", self)
        self.overlays_view.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.overlays_view)

        # App Store View (placeholder)
        self.appstore_view = QLabel("App Store View (Coming Soon)", self)
        self.appstore_view.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.appstore_view)

        # Highlighter View (placeholder)
        self.highlighter_view = QLabel("Highlighter View (Coming Soon)", self)
        self.highlighter_view.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.highlighter_view)

        # Settings View
        self.settings_view = self.create_settings_view()
        self.stack.addWidget(self.settings_view)

        # Add the sidebar and stacked widget to the main layout
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.sidebar)
        h_layout.addWidget(self.stack)

        main_layout.addLayout(h_layout)

        # Timer for updating the preview
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_preview)

        # Connect sidebar selection to the stacked widget
        self.sidebar.currentRowChanged.connect(self.switch_view)

        # Initialize the sidebar selection
        self.sidebar.setCurrentRow(0)

        # Create the connection status labels and arrange them vertically
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

        # Add buttons for RTMP server control
        self.start_rtmp_button = QPushButton("Start RTMP Server", self)
        self.start_rtmp_button.clicked.connect(self.start_local_rtmp_server)
        self.stop_rtmp_button = QPushButton("Stop RTMP Server", self)
        self.stop_rtmp_button.clicked.connect(self.stop_local_rtmp_server)

        rtmp_button_layout = QHBoxLayout()
        rtmp_button_layout.addWidget(self.start_rtmp_button)
        rtmp_button_layout.addWidget(self.stop_rtmp_button)

        main_layout.addLayout(status_layout)
        main_layout.addLayout(rtmp_button_layout)

        self.setLayout(main_layout)

        # Check RTMP Server Status
        self.check_rtmp_server_status()

    def switch_view(self, index):
        self.stack.setCurrentIndex(index)

    def create_editor_view(self):
        editor_layout = QVBoxLayout()

        # Create a combo box for source selection
        self.source_combo = QComboBox(self)
        self.source_combo.addItems(["Screen Capture", "Webcam", "Window Capture"])
        editor_layout.addWidget(self.source_combo)

        # Create the preview label with a fixed size
        self.preview_label = QLabel("Stream Preview", self)
        self.preview_label.setFixedSize(800, 450)  # Fixed size
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #2b2b2b; color: #ffffff; border: 1px solid #444444;")
        editor_layout.addWidget(self.preview_label)

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

    def create_settings_view(self):
        settings_layout = QFormLayout()

        # Create settings fields
        self.rtmp_url_input = QLineEdit(self)
        self.rtmp_url_input.setText(self.config.get('Streaming', 'rtmp_url', fallback='rtmp://localhost/live'))
        settings_layout.addRow('Stream RTMP URL:', self.rtmp_url_input)

        self.stream_key_input = QLineEdit(self)
        self.stream_key_input.setText(self.config.get('Streaming', 'stream_key', fallback='your_stream_key'))
        settings_layout.addRow('Stream RTMP Key:', self.stream_key_input)

        self.video_res_input = QComboBox(self)
        self.video_res_input.addItems(["1920x1080", "1280x720", "640x480"])
        self.video_res_input.setCurrentText(self.config.get('Video', 'resolution', fallback='1920x1080'))
        settings_layout.addRow('Streaming Resolution:', self.video_res_input)

        self.audio_human_input_device = QComboBox(self)
        self.audio_human_input_device.addItems(self.audio_devices["Recording"])
        settings_layout.addRow('Human Audio Input Device:', self.audio_human_input_device)

        self.system_audio_input_device = QComboBox(self)
        self.system_audio_input_device.addItems(self.audio_devices["Playback"])
        settings_layout.addRow('System Audio Input Device:', self.system_audio_input_device)

        self.local_rtmp_server_input = QLineEdit(self)
        self.local_rtmp_server_input.setText(self.config.get('RTMP', 'server', fallback='localhost'))
        settings_layout.addRow('Local RTMP Server:', self.local_rtmp_server_input)

        self.local_rtmp_port_input = QLineEdit(self)
        self.local_rtmp_port_input.setText(self.config.get('RTMP', 'port', fallback='1935'))
        settings_layout.addRow('Local RTMP Port:', self.local_rtmp_port_input)

        save_button = QPushButton("Save Settings", self)
        save_button.clicked.connect(self.save_settings)
        settings_layout.addRow(save_button)

        settings_widget = QWidget()
        settings_widget.setLayout(settings_layout)

        return settings_widget

    def save_settings(self):
        self.config['Streaming'] = {
            'rtmp_url': self.rtmp_url_input.text(),
            'stream_key': self.stream_key_input.text()
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
        with open(config_file, 'w') as configfile:
            self.config.write(configfile)
        logger.info("Settings saved.")

        # Update the application state to use the new settings
        self.update_application_settings()

    def update_application_settings(self):
        self.rtmp_url = self.config.get('Streaming', 'rtmp_url')
        self.stream_key = self.config.get('Streaming', 'stream_key')
        self.video_res = self.config.get('Video', 'resolution')
        self.local_rtmp_server = self.config.get('RTMP', 'server')
        self.local_rtmp_port = self.config.get('RTMP', 'port')

    def switch_source(self):
        source = self.source_combo.currentText()
        if source == "Screen Capture":
            self.start_screen_capture()

    def start_screen_capture(self):
        # Capture the selected monitor
        screen_width, screen_height = 1920, 1080  # Adjust these values if necessary

        # Start screen capture with FFmpeg for internal preview
        capture_command = [
            'C:\\ProgrammingProjects\\StreamLiter\\ffmpeg\\bin\\ffmpeg.exe',
            '-video_size', f'{screen_width}x{screen_height}',
            '-framerate', '30',
            '-f', 'gdigrab',
            '-i', 'desktop',
            '-pix_fmt', 'bgr24',  # Ensure the correct format for OpenCV
            '-f', 'rawvideo', '-'
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

            self.timer.start(30)  # Set timer to update preview at the same FPS

        except Exception as e:
            self.connection_status_label.setText("Connection Status: Error Occurred")
            self.connection_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Failed to start screen capture: {e}")

    def update_preview(self):
        try:
            if self.ffmpeg_process and self.ffmpeg_process.stdout:
                raw_frame = self.ffmpeg_process.stdout.read(1920 * 1080 * 3)
                if len(raw_frame) == 1920 * 1080 * 3:
                    frame = np.frombuffer(raw_frame, np.uint8).reshape((1080, 1920, 3))
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    # Resize the frame to fit the preview label size
                    frame = cv2.resize(frame, (self.preview_label.width(), self.preview_label.height()))

                    img = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_RGB888)
                    self.preview_label.setPixmap(QPixmap.fromImage(img))
                else:
                    logger.warning("No frame captured for preview.")
        except Exception as e:
            self.connection_status_label.setText("Connection Status: Error Occurred")
            self.connection_status_label.setStyleSheet("font: 16px; color: red;")
            logger.error(f"Error updating preview: {e}")

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

    def start_streaming_thread(self):
        # Run the streaming in a separate thread
        streaming_thread = threading.Thread(target=self.start_streaming)
        streaming_thread.start()

    def start_streaming(self):
        screen_width, screen_height = 1920, 1080  # Set screen dimensions
        rtmp_url = f"rtmp://127.0.0.1:1935/live/test"  # RTMP server URL

        capture_command = [
            'C:\\ProgrammingProjects\\StreamLiter\\ffmpeg\\bin\\ffmpeg.exe',
            '-video_size', f'{screen_width}x{screen_height}',
            '-framerate', '30',
            '-f', 'gdigrab',
            '-i', 'desktop',
            '-pix_fmt', 'bgr24',
            '-f', 'flv',  # Stream format for RTMP
            rtmp_url
        ]

        try:
            logger.info(f"Starting FFmpeg with command: {' '.join(capture_command)}")
            self.streaming_status_label.setText("Streaming Status: Streaming...")
            self.streaming_status_label.setStyleSheet("font: 16px; color: green;")

            self.ffmpeg_process = subprocess.Popen(
                capture_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE  # Capture FFmpeg's stderr output
            )

            self.timer.start(30)  # Update preview at the same FPS

        except Exception as e:
            self.streaming_status_label.setText("Streaming Status: Error Occurred")
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
                self.start_local_rtmp_server()
                time.sleep(3)  # Give the server time to start

                # Re-check the status
                self.check_rtmp_server_status()
                if self.local_rtmp_status_label.text() != "Local RTMP Server: Running":
                    self.streaming_status_label.setText("Streaming Status: Error - RTMP Server Not Running")
                    self.streaming_status_label.setStyleSheet("font: 16px; color: red;")
                    logger.error("Failed to start RTMP server.")
                    return

            # If RTMP server is running, start streaming
            logger.info("Starting test stream...")
            rtmp_url = f"rtmp://127.0.0.1:1935/live/test"
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
