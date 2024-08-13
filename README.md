
# StreamLiter

StreamLiter is a lightweight application designed to capture audio and video directly from your screen and stream it to an RTMP server. The application is built with PyQt5 for the GUI and integrates ZeroMQ for real-time frame publishing to reduce latency.

## Features

- Screen Capture and Streaming
- Real-time preview with reduced latency
- Adjustable streaming quality settings (High, Medium, Low)
- Customizable FFmpeg encoding parameters
- Local RTMP server setup using NGINX-RTMP
- Easy-to-use GUI built with PyQt5

## Requirements

Before running StreamLiter, ensure the following dependencies and tools are installed on your system:

### Python Dependencies

Install the necessary Python packages using pip:

```bash
pip install -r requirements.txt
```

The main Python dependencies include:

- PyQt5
- OpenCV
- Requests
- Psutil
- ZeroMQ (pyzmq)

### FFmpeg

Download the latest FFmpeg binaries from [this link](https://github.com/BtbN/FFmpeg-Builds/releases). Extract the files and place them in the `ffmpeg` directory under the main project folder. Ensure the path to `ffmpeg.exe` is correctly set in the application code.

### NGINX-RTMP

Download the NGINX-RTMP Windows binaries from [this link](https://github.com/illuspas/nginx-rtmp-win32). Extract the files and place them in the `nginx` directory under the main project folder. Ensure the path to `nginx.exe` is correctly set in the application code.

## Usage

1. Configure the settings in the `config.ini` file or through the application's settings menu.
2. Start the local RTMP server using the GUI.
3. Select your source (Screen Capture, Webcam, etc.) and start the preview.
4. Click "Go Live" to start streaming to the configured RTMP server.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

Special thanks to the maintainers of the FFmpeg and NGINX-RTMP projects. Please ensure to download these dependencies from their respective repositories to support the developers.
