from ultralytics import YOLO
import cv2

model = YOLO('best.onnx') 

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame.")
        break  

    gray_image = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    gray_image_3d = cv2.merge([gray_image, gray_image, gray_image]) 
    
    results = model(gray_image_3d)
    result = results[0]

    try:
        annotated_frame = result.plot()
    except AttributeError:
        print("Error: plot() method not available for results.")
        break
    
    cv2.imshow('YOLO Inference', annotated_frame)
    
    if cv2.waitKey(1) == 27: 
        break

cap.release()
cv2.destroyAllWindows()
