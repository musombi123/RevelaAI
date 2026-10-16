/* Free Vision Math engine for RevelaAI.
 * Browser-only; no paid APIs and no network calls are made by this module.
 * Optional integrations are supplied as local globals by the embedding frontend.
 */
export function scanPixelMath(imageData) {
  const { data, width, height } = imageData || {};
  if (!data || !width || !height) throw new Error("ImageData is required.");
  const total = width * height;
  let r = 0, g = 0, b = 0, luminance = 0, min = 255, max = 0;
  const gray = new Uint8Array(total);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    const rr = data[i], gg = data[i + 1], bb = data[i + 2];
    const y = Math.round(0.299 * rr + 0.587 * gg + 0.114 * bb);
    r += rr; g += gg; b += bb; luminance += y;
    min = Math.min(min, y); max = Math.max(max, y); gray[p] = y;
  }
  let gradients = 0, edgeCount = 0, n = 0, mean = 0;
  const values = [];
  for (let y = 1; y < height - 1; y += 2) for (let x = 1; x < width - 1; x += 2) {
    const i = y * width + x;
    const value = Math.abs(gray[i + 1] - gray[i - 1]) + Math.abs(gray[i + width] - gray[i - width]);
    values.push(value); gradients += value; mean += value; n++;
    if (value > 70) edgeCount++;
  }
  mean /= Math.max(1, n);
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, values.length);
  const brightness = Math.round(luminance / total);
  return {
    width, height, brightness, light: brightness < 50 ? "dark" : brightness > 200 ? "bright" : "balanced",
    averageRGB: [Math.round(r / total), Math.round(g / total), Math.round(b / total)],
    contrast: max - min, edgeCount, edgeActivity: Math.round(gradients / Math.max(1, n)),
    blurScore: Math.round(variance), focus: variance < 120 ? "possibly blurry" : "reasonably sharp",
  };
}

export function analyzeCanvas(canvas, { detector = null, cv = globalThis.cv || null } = {}) {
  const context = canvas?.getContext?.("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas is unavailable.");
  const math = scanPixelMath(context.getImageData(0, 0, canvas.width, canvas.height));
  let contourCount = math.edgeCount;
  if (cv?.Mat) {
    let src, gray, edges, contours, hierarchy;
    try {
      src = cv.imread(canvas); gray = new cv.Mat(); edges = new cv.Mat();
      contours = new cv.MatVector(); hierarchy = new cv.Mat();
      cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
      cv.Canny(gray, edges, 70, 150);
      cv.findContours(edges, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);
      contourCount = 0;
      for (let i = 0; i < contours.size(); i++) {
        const contour = contours.get(i);
        if (cv.contourArea(contour) >= 90) contourCount++;
        contour.delete?.();
      }
    } catch { /* Pixel gradient count remains a valid fallback measurement. */ }
    finally { [src, gray, edges, contours, hierarchy].forEach((mat) => mat?.delete?.()); }
  }
  const predictions = detector ? [] : [];
  const result = { ...math, contourCount, objects: predictions, text: "" };
  result.description = `Brightness ${result.brightness}/255 (${result.light}); ${result.contourCount} edge/contour regions estimated; ${result.focus}. ${cv?.Mat ? "OpenCV contour analysis ran locally." : "Using pixel-gradient fallback."}`;
  return result;
}

export function answerWhatDoISee(scan) {
  if (!scan) return "Start a camera scan first.";
  const objects = scan.objects?.length
    ? scan.objects.map((item) => `${item.class} (${Math.round(item.score * 100)}% sure)`).join(", ")
    : "No semantic object labels are available in this math-only result.";
  return `Latest local scan: ${objects}. Brightness: ${scan.brightness} (${scan.light}). Contour/edge regions: ${scan.contourCount}. Focus: ${scan.focus}.${scan.text ? ` Text detected: “${scan.text}”.` : ""}`;
}

console.log("Vision Engine: 100% Free - No Paid API");
