# 情绪识别子模块（YOLOv11 Face Emotion）

> **子模块**：本目录为 YOLOv11 人脸情绪识别独立 demo（`app.py`），是根项目 [AI-Vision-Guardian](../README.md) 情绪识别弹窗的后端训练参考。
>
> 完整项目文档（系统架构、快速开始、TTS 工程要点等）请查阅根目录 [README.md](../README.md)。

![image](val_batch1_pred.jpg)
## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [License](#license)
- [Contributing](#contributing)

## Features

- Real-time face emotion detection.
- Custom-trained YOLOv11 model for improved accuracy.
- Supports detection of five emotion classes.

## Installation

To get started, clone the repository and install the required packages.

```bash
git clone https://github.com/alihassanml/Yolo11-Face-Emotion-Detection.git
cd Yolo11-Face-Emotion-Detection
pip install -r requirements.txt
```

Make sure you have the following dependencies installed:

- Python 3.x
- OpenCV
- Ultralytics YOLO

## Usage

To run the model for face emotion detection, use the following script:

```python
from ultralytics import YOLO
import cv2

# Load the trained model
model = YOLO('best.onnx') 

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame.")
        break  

    # Convert the frame to grayscale
    gray_image = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Convert grayscale to 3-channel image
    gray_image_3d = cv2.merge([gray_image, gray_image, gray_image]) 
    
    # Perform inference
    results = model(gray_image_3d)
    result = results[0]

    # Plot results
    try:
        annotated_frame = result.plot()
    except AttributeError:
        print("Error: plot() method not available for results.")
        break
    
    # Display the output
    cv2.imshow('YOLO Inference', annotated_frame)
    
    if cv2.waitKey(1) == 27:  # ESC key to exit
        break

cap.release()
cv2.destroyAllWindows()
```

## Visualization

The results are visualized using OpenCV, displaying the detected emotions in real-time.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for discussion.

---

Feel free to edit the sections to match your project details better. You can also include screenshots or visualizations in the README for added clarity and engagement!
