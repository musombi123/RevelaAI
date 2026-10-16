# RevelaAI Free Vision Math

This folder contains a reusable browser-side computer-vision baseline. It is deliberately independent from the Flask/API runtime: camera frames stay in the browser and are not sent to this repository's server.

## Functions

- `scanPixelMath(ImageData)`: luminance, average RGB, contrast range, gradient activity and a blur heuristic.
- `analyzeCanvas(canvas, { detector, cv })`: pixel analysis plus optional locally loaded OpenCV contour counting.
- `answerWhatDoISee(scan)`: creates a grounded natural-language summary of measured data.

## Offline contract

Do not add CDN script tags or API calls here. The frontend must bundle the JavaScript, model JSON/weight shards, OpenCV WASM and OCR trained data under its own static asset directory for a fully offline first launch. The browser can only identify semantic objects when a trained model is actually loaded; pixel math alone cannot determine that a shape is a book or bottle. OCR similarly requires a locally bundled Tesseract worker/core and language data.

TensorFlow.js COCO-SSD, MobileNet, face-landmarks and Tesseract are optional adapters for the frontend. Verify upstream licenses and model-weight redistribution terms before bundling. Facial landmarks do not reliably infer a person's internal emotion, and face processing should remain opt-in.
